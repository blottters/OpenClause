from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def install_gui_dependencies() -> None:
    requirements_file = Path(__file__).resolve().parent / "requirements_gui.txt"
    if not requirements_file.exists():
        return
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_file), "-q"],
        check=True,
    )


def find_open_port(candidates: list[int]) -> int:
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No available port in the configured range.")


def open_browser(port: int) -> None:
    time.sleep(2)
    webbrowser.open(f"http://localhost:{port}")


def main() -> None:
    try:
        install_gui_dependencies()
    except Exception as exc:
        print(f"Failed to install GUI dependencies: {exc}")
        print("Please run: pip install -r requirements_gui.txt")
        sys.exit(1)

    port = find_open_port([8765, 8766, 8767, 8768])
    url = f"http://localhost:{port}"
    print(f"Starting OpenManus GUI at {url}")

    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    import uvicorn
    from gui.server import app

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
