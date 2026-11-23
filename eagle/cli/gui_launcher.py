"""Keep the GUI service independent of its launcher terminal."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from http.client import HTTPConnection, HTTPException
from pathlib import Path


INSTANCE_PATH = "/api/gui-instance"
SHUTDOWN_PATH = "/api/shutdown"


def _request(port: int, path: str, *, token: str | None = None) -> dict | None:
    connection = HTTPConnection("127.0.0.1", port, timeout=0.3)
    try:
        try:
            connection.connect()
        except (ConnectionRefusedError, TimeoutError):
            # Windows can retry a loopback connection before reporting refusal.
            return None
        connection.sock.settimeout(2)
        if token is None:
            connection.request("GET", path)
        else:
            connection.request("POST", path, b"{}", headers={
                "Origin": f"http://127.0.0.1:{port}",
                "X-Eagle-Token": token,
            })
        with connection.getresponse() as response:
            if response.status != 200:
                raise ValueError(f"Port {port} did not accept the EAGLE GUI request.")
            instance = json.load(response)
            if not isinstance(instance, dict):
                raise ValueError(f"Port {port} returned an invalid EAGLE GUI response.")
            return instance
    except ConnectionResetError:
        if token is not None:
            raise
        return None
    finally:
        connection.close()


def _start_service(root: Path, port: int, runs_roots: list[Path], log: Path) -> subprocess.Popen:
    args = [sys.executable, "-u", "-m", "eagle", "gui", "--serve", "--port", str(port)]
    for path in runs_roots:
        args.extend(("--runs-root", str(path)))
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        # An independent console also lets the service send Ctrl+Break to its jobs.
        options = {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": startup}
    else:
        options = {"start_new_session": True}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as stream:
        return subprocess.Popen(
            args, cwd=root, stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, **options,
        )


def _wait_for_service(port: int, process: subprocess.Popen, log: Path) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        instance = _request(port, INSTANCE_PATH)
        if instance is not None:
            return instance
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise ValueError(f"GUI service did not start. See {log}")


def _validate_instance(instance: dict, root: Path, runs_roots: list[Path], port: int) -> str:
    token = instance.get("token")
    if instance.get("root") != str(root) or not isinstance(token, str):
        raise ValueError(f"Port {port} belongs to another GUI or service. Choose a different --port.")
    if not {str(path) for path in runs_roots}.issubset(instance.get("runs_roots", ())):
        raise ValueError(f"The GUI on port {port} has different run folders. Choose a different --port.")
    return token


def supervise_gui(root: Path, port: int, runs_roots: list[Path], open_browser: Callable[[str], None] | None) -> int:
    """Reattach after a window closes and request orderly shutdown on Ctrl+C."""
    process = None
    token = None
    log = root / "logs/gui" / f"service-{port}.log"
    runs_roots = [path.expanduser().resolve() for path in runs_roots]
    try:
        instance = _request(port, INSTANCE_PATH)
        if instance is None:
            process = _start_service(root, port, runs_roots, log)
            instance = _wait_for_service(port, process, log)
        token = _validate_instance(instance, root, runs_roots, port)
        url = f"http://127.0.0.1:{port}"
        print(f"EAGLE GUI: {url}\nClosing a window leaves the experiment running. Ctrl+C stops the experiment and GUI.", flush=True)
        if open_browser is not None:
            open_browser(url)
        while (instance := _request(port, INSTANCE_PATH)) is not None and instance.get("token") == token:
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        try:
            if token is None and process is not None:
                token = _validate_instance(_wait_for_service(port, process, log), root, runs_roots, port)
            if token is not None:
                _request(port, SHUTDOWN_PATH, token=token)
                print("Stopping the experiment and GUI.", flush=True)
                if process is not None:
                    process.wait(timeout=35)
            return 0
        except (OSError, ValueError, HTTPException, subprocess.TimeoutExpired) as exc:
            print(f"GUI shutdown: {exc}", file=sys.stderr)
            return 2
    except (OSError, ValueError, HTTPException) as exc:
        print(f"Cannot open GUI: {exc}", file=sys.stderr)
        return 2
