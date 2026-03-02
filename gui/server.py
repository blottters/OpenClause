from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.mcp import MCPAgent
from app.agent.manus import Manus
from app.config import config
from app.flow.flow_factory import FlowFactory, FlowType
from gui import config_manager, session_manager

CallbackType = Callable[[dict[str, Any]], Awaitable[None]]

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="OpenManus GUI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class StreamManus(Manus):
    ws_callback: CallbackType | None = None

    async def think(self) -> bool:
        if self.ws_callback:
            await self.ws_callback({"type": "status", "state": "thinking"})
        should_act = await super().think()
        if self.ws_callback:
            last = self.memory.messages[-1] if self.memory.messages else None
            if last and last.content:
                await self.ws_callback(
                    {
                        "type": "agent_message",
                        "content": last.content,
                        "step": self.current_step,
                        "step_type": "think",
                    }
                )
            for call in self.tool_calls:
                args: Any
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = call.function.arguments
                await self.ws_callback(
                    {
                        "type": "tool_call",
                        "tool_name": call.function.name,
                        "arguments": args,
                    }
                )
        return should_act

    async def act(self) -> str:
        if self.ws_callback:
            await self.ws_callback({"type": "status", "state": "acting"})
        result = await super().act()
        if self.ws_callback:
            await self.ws_callback(
                {
                    "type": "agent_message",
                    "content": result,
                    "step": self.current_step,
                    "step_type": "act",
                }
            )
            if self.tool_calls:
                for message in self.memory.messages[-len(self.tool_calls) :]:
                    if message.role == "tool" and message.name:
                        await self.ws_callback(
                            {
                                "type": "tool_result",
                                "tool_name": message.name,
                                "result": message.content,
                            }
                        )
        return result


class StreamMCP(MCPAgent):
    ws_callback: CallbackType | None = None

    async def think(self) -> bool:
        if self.ws_callback:
            await self.ws_callback({"type": "status", "state": "thinking"})
        return await super().think()

    async def act(self) -> str:
        if self.ws_callback:
            await self.ws_callback({"type": "status", "state": "acting"})
        return await super().act()


def _reload_runtime_config() -> None:
    config._load_initial_config()  # noqa: SLF001


def _error_message(exc: Exception) -> str:
    text = str(exc)
    lower = text.lower()
    if "api" in lower and ("key" in lower or "auth" in lower or "401" in lower):
        return "API authentication failed. Check your key in Settings."
    return text


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def get_config() -> JSONResponse:
    payload = await asyncio.to_thread(config_manager.load_config)
    return JSONResponse(payload)


@app.post("/api/config")
async def set_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        await asyncio.to_thread(config_manager.save_config, body)
        await asyncio.to_thread(_reload_runtime_config)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/config/defaults")
async def get_defaults() -> dict[str, Any]:
    return await asyncio.to_thread(config_manager.load_defaults)


@app.get("/api/config/metadata")
async def get_metadata() -> dict[str, Any]:
    return await asyncio.to_thread(config_manager.get_config_metadata)


@app.get("/api/sessions")
async def sessions() -> list[dict[str, Any]]:
    return await asyncio.to_thread(session_manager.get_sessions)


@app.get("/api/sessions/{session_id}")
async def session_messages(session_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(session_manager.get_session_messages, session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    await asyncio.to_thread(session_manager.delete_session, session_id)
    return {"success": True}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    status_state = getattr(app.state, "agent_state", "idle")
    return {
        "status": status_state,
        "session_id": getattr(app.state, "session_id", None),
        "message": getattr(app.state, "status_message", "Ready"),
    }


async def _run_agent(mode: str, prompt: str, callback: CallbackType) -> str:
    if mode == "manus":
        agent = await StreamManus.create()
        agent.ws_callback = callback
        try:
            return await agent.run(prompt)
        finally:
            await agent.cleanup()

    if mode == "flow":
        agent = await StreamManus.create()
        agent.ws_callback = callback
        flow = FlowFactory.create_flow(flow_type=FlowType.PLANNING, agents={"manus": agent})
        try:
            return await flow.execute(prompt)
        finally:
            await agent.cleanup()

    if mode == "mcp":
        agent = StreamMCP()
        agent.ws_callback = callback
        try:
            await agent.initialize(
                connection_type="stdio",
                command=sys.executable,
                args=["-m", config.mcp_config.server_reference],
            )
            return await agent.run(prompt)
        finally:
            await agent.cleanup()

    raise HTTPException(status_code=400, detail=f"Unsupported mode: {mode}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    lock = asyncio.Lock()
    current_task: asyncio.Task[Any] | None = None

    async def send_event(payload: dict[str, Any]) -> None:
        async with lock:
            await websocket.send_json(payload)

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "start_task":
                if current_task and not current_task.done():
                    await send_event({"type": "error", "message": "A task is already running."})
                    continue

                prompt = (message.get("prompt") or "").strip()
                if not prompt:
                    continue
                mode = (message.get("mode") or "manus").strip().lower()
                incoming_session_id = message.get("session_id")
                if incoming_session_id:
                    session_id = incoming_session_id
                else:
                    session_id = await asyncio.to_thread(session_manager.create_session, mode)
                    await send_event({"type": "session_created", "session_id": session_id})

                await asyncio.to_thread(session_manager.add_message, session_id, "user", prompt, None, "user")
                if not incoming_session_id:
                    await asyncio.to_thread(session_manager.update_session_title, session_id, prompt)

                app.state.agent_state = "running"
                app.state.session_id = session_id
                app.state.status_message = "Running"

                async def runner() -> None:
                    try:
                        result = await _run_agent(mode, prompt, send_event)
                        await asyncio.to_thread(
                            session_manager.add_message,
                            session_id,
                            "assistant",
                            result,
                            None,
                            "result",
                        )
                        await send_event({"type": "task_complete", "final_output": result})
                        await send_event({"type": "status", "state": "idle"})
                    except asyncio.CancelledError:
                        await asyncio.to_thread(
                            session_manager.add_message,
                            session_id,
                            "system",
                            "Task stopped by user.",
                            None,
                            "system",
                        )
                        await send_event({"type": "agent_message", "content": "Task stopped by user.", "step_type": "system"})
                        await send_event({"type": "status", "state": "idle"})
                        raise
                    except Exception as exc:
                        msg = _error_message(exc)
                        await asyncio.to_thread(
                            session_manager.add_message,
                            session_id,
                            "error",
                            msg,
                            None,
                            "error",
                        )
                        await send_event({"type": "error", "message": msg})
                        await send_event({"type": "status", "state": "error"})
                    finally:
                        app.state.agent_state = "idle"
                        app.state.status_message = "Ready"

                current_task = asyncio.create_task(runner())

            elif msg_type == "stop_task":
                if current_task and not current_task.done():
                    current_task.cancel()
                    await send_event({"type": "status", "state": "idle"})

    except WebSocketDisconnect:
        if current_task and not current_task.done():
            current_task.cancel()
