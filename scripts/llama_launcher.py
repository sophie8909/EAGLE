#!/usr/bin/env python3
"""Launch one local llama.cpp profile and update the shared endpoint handoff."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eagle.llm_profiles import DEFAULT_CONTEXT_SIZE, DEFAULT_ENDPOINT_CONFIG_PATH, DEFAULT_PROFILES, LLMProfile, update_endpoint_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch one EAGLE llama.cpp LLM profile.")
    parser.add_argument("--profile", choices=("general", "coder"), required=True)
    parser.add_argument("--alias", default=None, help="OpenAI-compatible model alias sent to EAGLE.")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--context-size", type=int, default=DEFAULT_CONTEXT_SIZE)
    parser.add_argument("--model-path", type=Path, default=None, help="Actual local .gguf path; never written to Git.")
    parser.add_argument("--server-path", type=Path, default=None, help="Existing llama-server executable.")
    parser.add_argument("--endpoint-config", type=Path, default=DEFAULT_ENDPOINT_CONFIG_PATH)
    parser.add_argument("--lan-ip", default=None, help="Coder client IP to publish when multiple private interfaces exist.")
    args = parser.parse_args()
    defaults = DEFAULT_PROFILES[args.profile]
    alias = args.alias or defaults["model"]
    port = args.port or int(defaults["port"])
    bind_host = str(defaults["bind_host"])
    model_path = args.model_path or Path(input(f"Path to the actual {alias} .gguf file: ").strip())
    server_path = args.server_path or Path(os.environ.get("LLAMA_SERVER_PATH", "llama-server"))
    _validate_model_path(model_path)
    if args.context_size < 1 or not 1 <= port <= 65535:
        raise SystemExit("context size and port must be positive; port must be in 1..65535")

    client_host = "127.0.0.1"
    if args.profile == "coder":
        client_host = args.lan_ip or choose_private_ipv4()
        if not client_host:
            raise SystemExit("No private LAN IPv4 address was detected; pass --lan-ip explicitly.")
        bind_host = "0.0.0.0"
    profile = LLMProfile(args.profile, f"http://{client_host}:{port}/v1", alias)
    local_config = _write_local_profile(args.profile, model_path, server_path, bind_host, port, args.context_size, alias)
    command = [str(server_path), "--model", str(model_path), "--alias", alias, "--ctx-size", str(args.context_size), "--host", bind_host, "--port", str(port)]
    process = subprocess.Popen(command)
    if not wait_for_health(f"http://127.0.0.1:{port}/health"):
        process.terminate()
        raise SystemExit("llama-server did not become healthy; endpoint config was not updated.")
    update_endpoint_profile(args.endpoint_config, profile)
    label = "Coder" if args.profile == "coder" else "General"
    print(f"{label} profile updated:")
    print(f"- {'LAN IP' if args.profile == 'coder' else 'Local port'}: {client_host if args.profile == 'coder' else port}")
    print(f"- Port: {port}")
    print(f"- Base URL: {profile.base_url}")
    print(f"- Model alias: {alias}")
    print(f"- Repository config path: {args.endpoint_config}")
    print(f"- Local protected config path: {local_config}")
    if args.profile == "coder":
        print(f"git add {args.endpoint_config}")
        print('git commit -m "chore(config): update coder LLM endpoint"')
        print("git push")
    else:
        print("python3 scripts/run_eagle.py --config configs/eagle_10x50.yaml")
    return 0


def choose_private_ipv4() -> str | None:
    candidates = sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if _is_private_ipv4(item[4][0])})
    if len(candidates) == 1:
        print(f"Detected private LAN IPv4: {candidates[0]}")
        return candidates[0]
    if candidates:
        print("Detected private LAN IPv4 addresses:")
        for index, value in enumerate(candidates, 1):
            print(f"  {index}. {value}")
        selected = input("Choose an address or enter a corrected private IPv4: ").strip()
        selected = candidates[int(selected) - 1] if selected.isdigit() and 1 <= int(selected) <= len(candidates) else selected
        if _is_private_ipv4(selected):
            return selected
    return None


def wait_for_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return True
        except Exception:  # noqa: BLE001 - launcher retries until timeout
            time.sleep(0.5)
    return False


def _write_local_profile(profile: str, model_path: Path, server_path: Path, bind_host: str, port: int, context_size: int, alias: str) -> Path:
    target = Path.home() / ".config" / "eagle-llm" / f"{profile}.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"LLAMA_SERVER_PATH={server_path}\nGGUF_MODEL_PATH={model_path}\nLLAMA_BIND_HOST={bind_host}\nLLAMA_PORT={port}\nLLAMA_CONTEXT_SIZE={context_size}\nLLAMA_MODEL_ALIAS={alias}\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def _validate_model_path(path: Path) -> None:
    if path.suffix.lower() != ".gguf" or not path.is_file():
        raise SystemExit(f"Model path must be an existing .gguf file: {path}")


def _is_private_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = tuple(int(item) for item in parts)
    except ValueError:
        return False
    if any(item < 0 or item > 255 for item in octets) or octets[0] == 127 or octets[0] >= 224:
        return False
    return octets[0] == 10 or octets[0] == 192 and octets[1] == 168 or octets[0] == 172 and 16 <= octets[1] <= 31


if __name__ == "__main__":
    sys.exit(main())
