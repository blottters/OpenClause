const state = { ws: null, reconnectDelay: 500, busy: false, currentSessionId: null, config: {}, defaults: {}, metadata: {}, apiReady: false };
const els = {
  chat: document.getElementById('chat'), prompt: document.getElementById('prompt'), send: document.getElementById('send'), stop: document.getElementById('stop'),
  status: document.getElementById('status'), sessions: document.getElementById('session-list'), newChat: document.getElementById('new-chat'), mode: document.getElementById('mode'),
  settingsModal: document.getElementById('settings-modal'), openSettings: document.getElementById('open-settings'), closeSettings: document.getElementById('close-settings'),
  saveSettings: document.getElementById('save-settings'), resetDefaults: document.getElementById('reset-defaults'), settingsContent: document.getElementById('settings-content'), tabs: document.getElementById('tabs'),
  banner: document.getElementById('api-banner'), title: document.getElementById('session-title')
};

function setStatus(s){els.status.textContent=s[0].toUpperCase()+s.slice(1);els.status.className=`status-pill status-${s}`;}
function updateInputState(){
  const disabled = state.busy || !state.apiReady;
  els.prompt.disabled = disabled; els.send.disabled = disabled;
  els.stop.style.display = state.busy ? 'inline-block' : 'none';
  if(!state.apiReady){els.prompt.placeholder='Configure API key in Settings';els.banner.style.display='block';}
  else {els.prompt.placeholder='Describe a task...';els.banner.style.display='none';}
}
function addMessage(type, content){
  const div=document.createElement('div');div.className=`msg ${type}`;
  if(type==='thinking' && !content){div.innerHTML=`Thinking <span class="thinking"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span>`;}
  else if(content && content.split('\n').length>500){const short=content.split('\n').slice(0,500).join('\n');div.innerHTML=`<details><summary>Show output</summary><pre>${escapeHtml(short)}\n\n...truncated...</pre></details>`;}
  else {div.textContent=content || '';}
  els.chat.appendChild(div);els.chat.scrollTop=els.chat.scrollHeight;
}
function escapeHtml(v){return v.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}

async function api(path, opts={}){const res=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});return await res.json();}

function connectWs(){
  const proto=location.protocol==='https:'?'wss':'ws';
  state.ws=new WebSocket(`${proto}://${location.host}/ws`);
  state.ws.onopen=()=>{state.reconnectDelay=500;};
  state.ws.onclose=()=>{setStatus('error');addMessage('system','Reconnecting...');setTimeout(connectWs, state.reconnectDelay);state.reconnectDelay=Math.min(state.reconnectDelay*2, 8000);};
  state.ws.onmessage=(event)=>{const msg=JSON.parse(event.data);handleWs(msg);};
}

function handleWs(msg){
  if(msg.type==='session_created'){state.currentSessionId=msg.session_id;loadSessions();}
  if(msg.type==='status'){setStatus(msg.state);state.busy=msg.state==='thinking'||msg.state==='acting'||msg.state==='running';updateInputState();if(msg.state==='thinking')addMessage('system','Thinking...');}
  if(msg.type==='agent_message'){const t=msg.step_type==='act'?'action':msg.step_type==='error'?'error':msg.step_type==='system'?'system':'agent';addMessage(t,msg.content);}
  if(msg.type==='tool_call'){addMessage('action',`Tool: ${msg.tool_name}\nArgs: ${JSON.stringify(msg.arguments,null,2)}`);}
  if(msg.type==='tool_result'){addMessage('tool-result',`Tool Result (${msg.tool_name})\n${msg.result}`);}
  if(msg.type==='task_complete'){addMessage('system','Task complete.');state.busy=false;setStatus('idle');updateInputState();loadSessions();}
  if(msg.type==='error'){addMessage('error',msg.message);state.busy=false;setStatus('idle');updateInputState();}
}

async function loadSessions(){const sessions=await api('/api/sessions');els.sessions.innerHTML='';sessions.forEach(s=>{const it=document.createElement('div');it.className='session-item'+(s.id===state.currentSessionId?' active':'');it.textContent=s.title||'Untitled';it.onclick=()=>openSession(s.id, s.title);it.oncontextmenu=async(e)=>{e.preventDefault();await api(`/api/sessions/${s.id}`,{method:'DELETE'});if(state.currentSessionId===s.id){state.currentSessionId=null;els.chat.innerHTML='';}loadSessions();};els.sessions.appendChild(it);});}
async function openSession(id,title){state.currentSessionId=id;els.title.value=title||'New Chat';els.chat.innerHTML='';(await api(`/api/sessions/${id}`)).forEach(m=>addMessage(m.step_type==='error'?'error':m.role==='user'?'user':m.step_type==='act'?'action':m.role==='system'?'system':'agent',m.content));loadSessions();}

function collectForm(){const out={};document.querySelectorAll('[data-path]').forEach(el=>{const path=el.dataset.path.split('.');let cur=out;for(let i=0;i<path.length-1;i++){cur[path[i]]=cur[path[i]]||{};cur=cur[path[i]];}const k=path[path.length-1];cur[k]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value);});return out;}
function buildSettings(section){els.settingsContent.innerHTML='';const fields=state.config[section]||{};const meta=(state.metadata[section]||{});
  Object.entries(fields).forEach(([k,v])=>{const m=meta[k]||{description:k,recommendation:''};const row=document.createElement('div');row.className='settings-row';const label=document.createElement('label');label.textContent=`${k} (?)`;label.title=m.description;const input=document.createElement('input');input.dataset.path=`${section}.${k}`;
    if(typeof v==='boolean'){input.type='checkbox';input.checked=v;} else if(typeof v==='number'){input.type='number';input.value=String(v);if(k==='temperature'){input.min='0';input.max='2';input.step='0.1';}if(k==='max_tokens'){input.min='1';}} else {input.type=k.includes('api_key')?'password':'text';input.value=v??'';}
    if(k==='base_url'){input.pattern='https?://.+';}
    const rec=document.createElement('div');rec.style.color='#6b7280';rec.style.fontSize='12px';rec.textContent=m.recommendation||m.description;
    row.append(label,input,rec);els.settingsContent.appendChild(row);
  });
}
function buildTabs(){els.tabs.innerHTML='';const keys=Object.keys(state.config);let active=keys[0]||'';keys.forEach(k=>{const b=document.createElement('button');b.className='tab'+(k===active?' active':'');b.textContent=k;b.onclick=()=>{[...els.tabs.children].forEach(c=>c.classList.remove('active'));b.classList.add('active');buildSettings(k);};els.tabs.appendChild(b);});if(active)buildSettings(active);}

async function loadConfig(){const cfg=await api('/api/config');state.config=cfg.data||{};state.defaults=await api('/api/config/defaults');state.metadata=await api('/api/config/metadata');
  const apiKey=(state.config.llm||{}).api_key||'';state.apiReady=!!apiKey && !String(apiKey).startsWith('YOUR_') && !String(apiKey).startsWith('sk-...');
  updateInputState();if(!state.apiReady){els.settingsModal.classList.add('open');}
}

els.newChat.onclick=()=>{state.currentSessionId=null;els.chat.innerHTML='';els.title.value='New Chat';};
els.send.onclick=()=>sendPrompt();
els.stop.onclick=()=>state.ws?.send(JSON.stringify({type:'stop_task'}));
els.openSettings.onclick=()=>{buildTabs();els.settingsModal.classList.add('open');};
els.closeSettings.onclick=()=>els.settingsModal.classList.remove('open');
els.resetDefaults.onclick=()=>{state.config=JSON.parse(JSON.stringify(state.defaults));buildTabs();};
els.saveSettings.onclick=async()=>{const payload=collectForm();const res=await api('/api/config',{method:'POST',body:JSON.stringify(payload)});if(res.success){state.config=payload;await loadConfig();alert('Settings saved successfully');} else alert(res.error||'Invalid configuration. Check your values.');};
document.getElementById('open-help').onclick=()=>alert('Enter task, choose mode, send. Right-click a session to delete.');
document.addEventListener('keydown',(e)=>{if(e.key==='Escape')els.settingsModal.classList.remove('open');});
els.prompt.addEventListener('keydown',(e)=>{if(e.key==='Enter' && !e.shiftKey){e.preventDefault();sendPrompt();}});
els.prompt.addEventListener('input',()=>{els.prompt.style.height='auto';els.prompt.style.height=Math.min(els.prompt.scrollHeight,180)+'px';});

function sendPrompt(){const prompt=els.prompt.value.trim();if(!prompt||state.busy||!state.apiReady)return;addMessage('user',prompt);state.busy=true;setStatus('thinking');updateInputState();state.ws.send(JSON.stringify({type:'start_task',prompt,mode:els.mode.value,session_id:state.currentSessionId||undefined}));els.prompt.value='';}

(async function init(){connectWs();await loadConfig();await loadSessions();})();
