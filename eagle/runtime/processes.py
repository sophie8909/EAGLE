"""Safe management of one local llama-server and one watchdog."""
from __future__ import annotations
import os, signal, socket, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path
from .config import RuntimeConfig
from .endpoints import health_check, write_resolved_endpoint

@dataclass(frozen=True)
class ProcessStatus:
    state: str
    detail: str
    pid: int|None=None

def build_server_command(runtime: RuntimeConfig) -> list[str]:
    llm=runtime.llm
    if llm.mode!="local" or llm.model is None or llm.server_binary is None or llm.host is None:
        raise ValueError("Cannot build a local LLM server command in remote mode.")
    a=llm.arguments
    return [str(llm.server_binary),"--host",llm.host,"--port",str(llm.port),"--model",str(llm.model),"--ctx-size",str(a.context_size),"--n-gpu-layers",str(a.gpu_layers),"--parallel",str(a.parallel),"--threads",str(a.threads),"--batch-size",str(a.batch_size)]

class RuntimeManager:
    def __init__(self,runtime:RuntimeConfig): self.runtime=runtime
    def start(self,*,include_watchdog=True)->list[ProcessStatus]:
        if self.runtime.llm.mode=="remote":
            ok,detail=health_check(self.runtime)
            if not ok: raise RuntimeError(f"Remote LLM endpoint unavailable at {self.runtime.llm.base_url}: {detail}")
            write_resolved_endpoint(self.runtime); return [ProcessStatus("healthy",detail)]
        status=self.start_server()
        write_resolved_endpoint(self.runtime)
        if include_watchdog and self.runtime.watchdog.enabled: self.start_watchdog()
        return [status]
    def start_server(self)->ProcessStatus:
        command=build_server_command(self.runtime); pid=self.read_pid("llm-server")
        if pid and process_alive(pid):
            if not command_matches(pid,command): raise RuntimeError(f"llm-server.pid points to an unrelated process: {pid}")
            ok,detail=health_check(self.runtime)
            if ok:return ProcessStatus("healthy",detail,pid)
            raise RuntimeError(f"Managed LLM server (PID {pid}) is unhealthy: {detail}")
        self.remove_pid("llm-server")
        if port_occupied(self.runtime.llm.client_host,self.runtime.llm.port): raise RuntimeError(f"Port {self.runtime.llm.client_host}:{self.runtime.llm.port} is occupied by an unrelated process.")
        log_path=self.runtime.log_root/"llm-server.log"
        with log_path.open("a",encoding="utf-8") as log:
            process=subprocess.Popen(command,cwd=self.runtime.project_root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,text=True)
        self.write_pid("llm-server",process.pid)
        deadline=time.monotonic()+self.runtime.watchdog.startup_timeout_seconds; detail="startup timeout"
        while time.monotonic()<deadline:
            if process.poll() is not None:
                self.remove_pid("llm-server"); raise RuntimeError(f"llama-server exited with code {process.returncode}; see {log_path}.")
            ok,detail=health_check(self.runtime,retries=1)
            if ok:return ProcessStatus("healthy",detail,process.pid)
            time.sleep(self.runtime.health_check.retry_delay_seconds)
        self.stop_server(); raise RuntimeError(f"llama-server failed startup health checks: {detail}")
    def stop(self)->None:
        self.stop_watchdog()
        if self.runtime.llm.mode=="local": self.stop_server()
        try:self.runtime.resolved_endpoint_path.unlink()
        except FileNotFoundError:pass
    def stop_server(self)->None:
        pid=self.read_pid("llm-server")
        if not pid or not process_alive(pid): self.remove_pid("llm-server"); return
        if not command_matches(pid,build_server_command(self.runtime)): raise RuntimeError(f"Refusing to stop unrelated process PID {pid}.")
        terminate_pid(pid,5.0); self.remove_pid("llm-server")
    def statuses(self)->list[ProcessStatus]:
        if self.runtime.llm.mode=="remote":
            ok,detail=health_check(self.runtime,retries=1); return [ProcessStatus("healthy" if ok else "unhealthy",detail)]
        pid=self.read_pid("llm-server")
        if not pid or not process_alive(pid): self.remove_pid("llm-server"); return [ProcessStatus("stopped","no live managed PID")]
        if not command_matches(pid,build_server_command(self.runtime)): return [ProcessStatus("unrelated","PID command line does not match",pid)]
        ok,detail=health_check(self.runtime,retries=1); return [ProcessStatus("healthy" if ok else "unhealthy",detail,pid)]
    def check(self)->list[ProcessStatus]:
        ok,detail=health_check(self.runtime); return [ProcessStatus("healthy" if ok else "unhealthy",detail)]
    def start_watchdog(self)->int:
        pid=self.read_pid("watchdog")
        if pid and process_alive(pid):
            if "eagle.runtime.watchdog" in read_command(pid): return pid
            raise RuntimeError(f"watchdog.pid points to an unrelated process: {pid}")
        self.remove_pid("watchdog")
        with (self.runtime.log_root/"watchdog.log").open("a",encoding="utf-8") as log:
            process=subprocess.Popen([sys.executable,"-m","eagle.runtime.watchdog","--config",str(self.runtime.source_path)],cwd=self.runtime.project_root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,text=True)
        self.write_pid("watchdog",process.pid); return process.pid
    def stop_watchdog(self)->None:
        pid=self.read_pid("watchdog")
        if not pid or not process_alive(pid): self.remove_pid("watchdog"); return
        if "eagle.runtime.watchdog" not in read_command(pid): raise RuntimeError(f"Refusing to stop unrelated watchdog PID {pid}.")
        terminate_pid(pid,5.0); self.remove_pid("watchdog")
    def pid_path(self,name): return self.runtime.pid_root/f"{name}.pid"
    def read_pid(self,name):
        try:return int(self.pid_path(name).read_text(encoding="ascii").strip())
        except (FileNotFoundError,OSError,ValueError):return None
    def write_pid(self,name,pid):
        path=self.pid_path(name); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+".tmp"); tmp.write_text(f"{pid}\n",encoding="ascii"); tmp.replace(path)
    def remove_pid(self,name):
        try:self.pid_path(name).unlink()
        except FileNotFoundError:pass

def read_command(pid):
    try:return "\0".join(part.decode("utf-8",errors="replace") for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part)
    except OSError:return ""
def command_matches(pid,expected): return read_command(pid).split("\0")==expected
def process_alive(pid):
    try:os.kill(pid,0)
    except (ProcessLookupError,OSError):return False
    except PermissionError:return True
    return pid>0
def port_occupied(host,port):
    try:
        with socket.create_connection((host,port),timeout=.25):return True
    except (ConnectionRefusedError,TimeoutError,socket.timeout,OSError):return False
def terminate_pid(pid,timeout):
    os.kill(pid,signal.SIGTERM); deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if not process_alive(pid):return
        time.sleep(.1)
    if process_alive(pid):os.kill(pid,signal.SIGKILL)

