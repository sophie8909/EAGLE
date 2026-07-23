#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

run_discovery() {
    local mode="$1"
    require_python3
    ensure_env_dirs
    echo "Scanning for GGUF models ($mode scan). This may take a while..."
    python3 - "$mode" "$REPO_ROOT" "$EXPERIMENT_ENV_DIR" "$REGISTRY_PATH" <<'PY'
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

mode, repo_root, env_dir, registry_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
model_root = env_dir / "model"

EXCLUDED_DIR_NAMES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv",
    "node_modules", "site-packages", "dist-packages",
}
EXCLUDED_PREFIXES = ("/proc", "/sys", "/dev", "/run")
EXCLUDED_FULL_PREFIXES = ("/snap",)
RELATED_NAMES = {
    "tokenizer.json", "tokenizer.model", "tokenizer_config.json",
    "config.json", "generation_config.json", "special_tokens_map.json",
    "chat_template.jinja", "params.json",
}


def existing_paths(paths):
    seen = set()
    for raw in paths:
        if not raw:
            continue
        path = Path(os.path.expanduser(str(raw))).resolve()
        text = str(path)
        if text in seen or not path.exists():
            continue
        seen.add(text)
        yield path


def mounted_storage_roots():
    try:
        result = subprocess.run(
            ["findmnt", "-rn", "-o", "TARGET,FSTYPE"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    roots = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        target = parts[0]
        fs_type = parts[1] if len(parts) > 1 else ""
        if fs_type in {"proc", "sysfs", "devtmpfs", "tmpfs", "cgroup2", "squashfs", "autofs"}:
            continue
        if target in {"/", str(repo_root)}:
            continue
        if target.startswith(EXCLUDED_PREFIXES) or target.startswith(EXCLUDED_FULL_PREFIXES):
            continue
        roots.append(target)
    return roots


def quick_roots():
    home = Path.home()
    return list(existing_paths([
        repo_root,
        home,
        home / ".cache" / "huggingface" / "hub",
        home / "models",
        home / "llama.cpp",
        home / "llama.cpp" / "models",
        "/opt/models",
        "/data",
        "/mnt",
        "/media",
        *mounted_storage_roots(),
    ]))


def should_skip_dir(path: Path) -> bool:
    text = str(path)
    if text.startswith(EXCLUDED_PREFIXES) or text.startswith(EXCLUDED_FULL_PREFIXES):
        return True
    if path.name in EXCLUDED_DIR_NAMES:
        return True
    return False


def scan_files(roots):
    seen_dirs = set()
    found = []
    for root in roots:
        root_text = str(root)
        if root_text in seen_dirs:
            continue
        seen_dirs.add(root_text)
        if root.is_file() and root.suffix.lower() == ".gguf":
            found.append(root)
            continue
        if not root.is_dir():
            continue
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = [
                name for name in dirnames
                if not should_skip_dir(current_path / name)
            ]
            for filename in filenames:
                if filename.lower().endswith(".gguf"):
                    found.append(current_path / filename)
    return found


def real(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        return path.absolute()


def is_mmproj(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered.startswith("mmproj") or "mmproj" in lowered or "projector" in lowered


def is_vocab_or_fixture(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered.startswith("ggml-vocab") or lowered.endswith(".gguf.inp") or lowered.endswith(".gguf.out")


def choose_alias(paths):
    def score(path: Path):
        text = str(path)
        value = 0
        if "/snapshots/" in text:
            value += 20
        if "/blobs/" in text:
            value -= 20
        if not re.fullmatch(r"[0-9a-f]{32,}", path.name.lower().removesuffix(".gguf")):
            value += 10
        if is_mmproj(path):
            value -= 5
        return value, -len(text)
    return sorted(paths, key=score, reverse=True)[0]


def split_key(path: Path):
    match = re.match(r"(.+)-(\d{5})-of-(\d{5})\.gguf$", path.name, re.IGNORECASE)
    if not match:
        return None
    return path.parent, match.group(1), int(match.group(3))


def infer_quant(name: str):
    matches = re.findall(r"(?:^|[-_.])((?:I?Q\d(?:_[A-Z0-9]+)+)|BF16|F16|F32)(?:[-_.]|$)", name, re.IGNORECASE)
    if not matches:
        return None
    return matches[-1].upper()


def infer_family(name: str):
    lowered = name.lower()
    for key, label in (
        ("qwen", "Qwen"),
        ("llama", "Llama"),
        ("mistral", "Mistral"),
        ("deepseek", "DeepSeek"),
        ("gemma", "Gemma"),
        ("phi", "Phi"),
        ("mixtral", "Mixtral"),
        ("codellama", "Code Llama"),
    ):
        if key in lowered:
            return label
    return None


def infer_params(name: str):
    match = re.search(r"(\d+(?:\.\d+)?)\s*[bB](?:[-_.]|$)", name)
    if not match:
        return None
    value = match.group(1)
    return f"{value}B"


def clean_display(path: Path, quant: str | None):
    stem = re.sub(r"-\d{5}-of-\d{5}$", "", path.stem)
    if quant:
        stem = re.sub(re.escape(quant), "", stem, flags=re.IGNORECASE)
        stem = re.sub(re.escape(quant.replace("_", "-")), "", stem, flags=re.IGNORECASE)
        stem = re.sub(re.escape(quant.replace("_", " ")), "", stem, flags=re.IGNORECASE)
    stem = stem.replace("_", " ").replace("-", " ")
    words = [word for word in stem.split() if word.upper() != (quant or "")]
    return " ".join(words).strip() or path.stem


def stable_id(display: str, quant: str | None, canonical: str):
    base = "-".join(part for part in [display, quant or ""] if part)
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    digest = hashlib.sha1(canonical.encode()).hexdigest()[:8]
    return f"{slug[:56]}-{digest}" if slug else f"model-{digest}"


def size_bytes(paths):
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def choose_mmproj(model_path: Path, mmprojs):
    same_dir = [item for item in mmprojs if item.parent == model_path.parent]
    candidates = same_dir or mmprojs
    if not candidates:
        return None
    model_tokens = set(re.findall(r"[a-z0-9]+", model_path.stem.lower()))
    scored = []
    for item in candidates:
        tokens = set(re.findall(r"[a-z0-9]+", item.stem.lower())) - {"mmproj", "projector", "bf16", "f16", "f32"}
        score = len(model_tokens & tokens)
        if item.parent == model_path.parent:
            score += 5
        scored.append((score, -len(str(item)), item))
    scored.sort(reverse=True)
    return scored[0][2] if scored and scored[0][0] > 0 else (same_dir[0] if same_dir else None)


def related_files(directory: Path):
    values = []
    for name in RELATED_NAMES:
        path = directory / name
        if path.exists():
            values.append(str(real(path)))
    return sorted(values)


def link_force(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        try:
            if target.resolve() == source:
                return
        except OSError:
            pass
        target.unlink()
    target.symlink_to(source)


def find_server():
    env = os.environ.get("LLAMA_SERVER_BIN")
    candidates = []
    if env:
        candidates.append(Path(env))
    path_hit = shutil.which("llama-server")
    if path_hit:
        candidates.append(Path(path_hit))
    candidates.extend([
        model_root / "llama-b9174" / "llama-server",
        model_root / "llama.cpp" / "build" / "bin" / "llama-server",
        model_root / "llama.cpp" / "llama.cpp" / "build" / "bin" / "llama-server",
        env_dir / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server",
        Path.home() / "llama.cpp" / "build" / "bin" / "llama-server",
    ])
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


roots = quick_roots() if mode == "quick" else [Path("/")]
scanned_files = scan_files(roots)
aliases_by_real = {}
for path in scanned_files:
    aliases_by_real.setdefault(real(path), []).append(path)

mmproj_real_paths = sorted([
    canonical for canonical, aliases in aliases_by_real.items()
    if any(is_mmproj(alias) for alias in aliases)
])
mmprojs = [choose_alias(aliases_by_real[path]) for path in mmproj_real_paths]
language_files = []
for canonical, aliases in aliases_by_real.items():
    if canonical in mmproj_real_paths:
        continue
    display_path = choose_alias(aliases)
    if is_vocab_or_fixture(display_path):
        continue
    language_files.append((canonical, display_path))

groups = {}
for canonical, display_path in language_files:
    key = split_key(display_path)
    if key is None:
        group_id = ("single", str(canonical))
    else:
        directory, base, total = key
        group_id = ("split", str(directory), base, total)
    groups.setdefault(group_id, []).append((canonical, display_path))

server = find_server()
models = []
for _, shard_pairs in groups.items():
    shard_pairs = sorted(shard_pairs, key=lambda item: item[1].name)
    shards = [item[0] for item in shard_pairs]
    display_paths = [item[1] for item in shard_pairs]
    primary = shards[0]
    display_path = display_paths[0]
    quant = infer_quant(display_path.name)
    display_base = clean_display(display_path, quant)
    params = infer_params(display_path.name) or infer_params(str(display_path.parent))
    family = infer_family(display_path.name) or infer_family(str(display_path.parent))
    display = display_base
    if params and params.lower() not in display.lower():
        display = f"{display} {params}"
    model_id = stable_id(display, quant, "|".join(str(item) for item in shards))
    model_dir = model_root / model_id
    organized_model = model_dir / "model.gguf"
    link_force(primary, organized_model)
    organized_shards = []
    for shard in shards:
        target = model_dir / shard.name
        link_force(shard, target)
        organized_shards.append(str(target.relative_to(env_dir)))
    mmproj_alias = choose_mmproj(display_path, mmprojs)
    mmproj = None if mmproj_alias is None else real(mmproj_alias)
    organized_mmproj = None
    if mmproj is not None:
        target = model_dir / "mmproj.gguf"
        link_force(mmproj, target)
        organized_mmproj = str(target.relative_to(env_dir))
    total_bytes = size_bytes(shards)
    source = str(primary)
    models.append({
        "stable_model_id": model_id,
        "display_name": display,
        "model_family": family,
        "parameter_size": params,
        "quantization": quant,
        "source_path": source,
        "display_source_path": str(display_path),
        "organized_model_path": str(organized_model.relative_to(env_dir)),
        "file_size_bytes": total_bytes,
        "size_gb": round(total_bytes / (1024 ** 3), 3),
        "shards": [str(item) for item in shards],
        "organized_shards": organized_shards,
        "mmproj_path": None if mmproj is None else str(mmproj),
        "display_mmproj_path": None if mmproj_alias is None else str(mmproj_alias),
        "organized_mmproj_path": organized_mmproj,
        "related_files": related_files(primary.parent),
        "llama_server_compatible": bool(server),
    })

models.sort(key=lambda item: (item.get("model_family") or "", item.get("display_name") or "", item.get("quantization") or ""))
payload = {
    "version": 1,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "hostname": socket.gethostname(),
    "scan_mode": mode,
    "scan_roots": [str(item) for item in roots],
    "llama_server_binary": server,
    "models": models,
    "ignored_mmproj_files": [str(item) for item in mmprojs],
}
registry_path.parent.mkdir(parents=True, exist_ok=True)
tmp = registry_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(registry_path)
print(f"Wrote {registry_path}")
print(f"Registered {len(models)} usable language model group(s).")
for index, model in enumerate(models, 1):
    quant = model.get("quantization") or "unknown quant"
    print(f"{index}. {model['display_name']} - {quant} - {model['size_gb']:.1f} GB")
PY
}

main_menu() {
    ensure_env_dirs
    while true; do
        print_header "Model Discovery"
        echo "1. Quick scan"
        echo "2. Full scan"
        echo "3. Show current model registry"
        echo "4. Return"
        local choice
        read -r -p "Choose an option [1-4]: " choice
        case "${choice:-}" in
            1) run_discovery quick; pause_for_enter ;;
            2) run_discovery full; pause_for_enter ;;
            3) show_registry || true; pause_for_enter ;;
            4) return 0 ;;
            *) echo "Invalid selection." ;;
        esac
    done
}

main_menu
