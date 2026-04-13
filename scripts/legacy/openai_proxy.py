#!/usr/bin/env python3
"""
Ollama-to-Cloud API Proxy

Translates Ollama /api/generate requests to OpenAI-compatible chat completion APIs.
This allows MicroRTS Java agents (which speak Ollama protocol) to use cloud models.

Supported providers:
    deepseek:  https://api.deepseek.com  (deepseek-chat, deepseek-reasoner)
    openai:    https://api.openai.com    (gpt-4o, gpt-4o-mini)
    openrouter: https://openrouter.ai    (any model)

Usage:
    API_KEY=sk-... python3 openai_proxy.py --provider deepseek [--port 11435]

Then set OLLAMA_HOST=http://localhost:11435 and OLLAMA_MODEL=deepseek-chat
"""

import json
import sys
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
import argparse
import time
import threading

PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
        "models": ["anthropic/claude-sonnet-4", "google/gemini-2.5-pro"],
    },
}

# Set at startup from args
API_KEY = ""
API_BASE_URL = ""
PROVIDER_NAME = ""

# Stats
stats = {"requests": 0, "errors": 0, "total_ms": 0}
stats_lock = threading.Lock()


class OllamaProxyHandler(BaseHTTPRequestHandler):
    """Handles Ollama-format requests and proxies to OpenAI."""

    def log_message(self, format, *args):
        """Custom logging to show model and timing."""
        pass  # Suppress default logs, we do our own

    def do_POST(self):
        if self.path == "/api/generate":
            self._handle_generate()
        elif self.path == "/api/tags":
            self._handle_tags()
        else:
            self.send_error(404, f"Unknown path: {self.path}")

    def do_GET(self):
        if self.path == "/api/tags":
            self._handle_tags()
        elif self.path == "/":
            # Health check
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Ollama-OpenAI proxy running\n")
        else:
            self.send_error(404)

    def _handle_tags(self):
        """Return model list for the configured provider."""
        provider = PROVIDERS.get(PROVIDER_NAME, {})
        models = [
            {"name": m, "size": 0, "modified_at": "2026-01-01T00:00:00Z"}
            for m in provider.get("models", [])
        ]
        self._send_json({"models": models})

    def _handle_generate(self):
        """Translate Ollama /api/generate to OpenAI chat completion."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            request = json.loads(body)

            model = request.get("model", "deepseek-chat")
            prompt = request.get("prompt", "")
            use_json = request.get("format") == "json"

            start_time = time.time()

            # Build OpenAI-compatible request
            messages = [
                {"role": "user", "content": prompt}
            ]

            api_request = {
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            }

            if use_json:
                api_request["response_format"] = {"type": "json_object"}

            # Call cloud API
            req_data = json.dumps(api_request).encode("utf-8")
            req = urllib.request.Request(
                API_BASE_URL,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                openai_response = json.loads(resp.read())

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Extract response text
            response_text = openai_response["choices"][0]["message"]["content"]

            # Build Ollama-format response
            ollama_response = {
                "model": model,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "response": response_text,
                "done": True,
                "total_duration": elapsed_ms * 1000000,  # nanoseconds
                "eval_count": openai_response.get("usage", {}).get("completion_tokens", 0),
                "prompt_eval_count": openai_response.get("usage", {}).get("prompt_tokens", 0),
            }

            with stats_lock:
                stats["requests"] += 1
                stats["total_ms"] += elapsed_ms

            print(f"  [proxy] {model} -> {elapsed_ms}ms, "
                  f"{openai_response.get('usage', {}).get('total_tokens', '?')} tokens "
                  f"(req #{stats['requests']})", flush=True)

            self._send_json(ollama_response)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            print(f"  [proxy] API error {e.code}: {error_body[:200]}", flush=True)
            with stats_lock:
                stats["errors"] += 1
            self.send_error(e.code, f"API error: {error_body[:200]}")

        except Exception as e:
            print(f"  [proxy] Error: {e}", flush=True)
            with stats_lock:
                stats["errors"] += 1
            self.send_error(500, str(e))

    def _send_json(self, data):
        response_bytes = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)


def main():
    global API_KEY, API_BASE_URL, PROVIDER_NAME

    parser = argparse.ArgumentParser(description="Ollama-to-Cloud API proxy")
    parser.add_argument("--port", type=int, default=11435, help="Port to listen on")
    parser.add_argument("--provider", default="deepseek",
                        choices=list(PROVIDERS.keys()),
                        help="Cloud API provider")
    parser.add_argument("--api-key", default=None, help="API key (or use env var)")
    args = parser.parse_args()

    PROVIDER_NAME = args.provider
    provider = PROVIDERS[args.provider]
    API_BASE_URL = provider["base_url"]

    # Get API key from arg, env, or fail
    API_KEY = args.api_key or os.environ.get(provider["env_key"], "")
    if not API_KEY:
        print(f"ERROR: No API key. Set {provider['env_key']} or use --api-key")
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", args.port), OllamaProxyHandler)
    print(f"Ollama-to-{args.provider} proxy on http://127.0.0.1:{args.port}")
    print(f"API: {API_BASE_URL}")
    print(f"Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"Models: {', '.join(provider['models'])}")
    print(f"Set OLLAMA_HOST=http://localhost:{args.port}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nProxy stats: {stats['requests']} requests, "
              f"{stats['errors']} errors, "
              f"{stats['total_ms']}ms total API time")
        server.shutdown()


if __name__ == "__main__":
    main()
