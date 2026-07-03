import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

# ===== CONFIG =====
PYTHON_CMD = [sys.executable, "-u", "-m", "eagle.main"]

CONFIGS_DIR = "configs/evolution/experiments/llm_interval"
# ===== SETUP =====
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_dir = Path("batch_logs") / timestamp
log_dir.mkdir(parents=True, exist_ok=True)

print(f"Batch start: {timestamp}", flush=True)
print(f"Logs: {log_dir}", flush=True)
print(flush=True)

# ===== RUN =====
config_files = sorted(
    config_file
    for config_file in os.listdir(CONFIGS_DIR)
    if config_file.endswith(".json")
)

if not config_files:
    print(f"No config files found in {CONFIGS_DIR}", flush=True)

for index, config_file in enumerate(config_files, start=1):
    config = os.path.join(CONFIGS_DIR, config_file)
    config_path = Path(config)

    if not config_path.exists():
        print(f"[SKIP] config not found: {config}", flush=True)
        continue

    config_name = config_path.stem

    run_name = f"{config_name}"
    log_file = log_dir / f"{run_name}.log"

    cmd = PYTHON_CMD + ["--config", config,]

    print("=" * 60, flush=True)
    print(f"[RUN {index}/{len(config_files)}] {run_name}", flush=True)
    print(f"[CMD] {' '.join(cmd)}", flush=True)
    print(f"[LOG] {log_file}", flush=True)
    print("=" * 60, flush=True)

    with open(log_file, "w") as f:
        try:
            start_time = time.perf_counter()
            child_env = os.environ.copy()
            child_env["PYTHONUNBUFFERED"] = "1"
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=child_env,
            )

            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)  # terminal
                f.write(line)                    # log
                f.flush()

            process.wait()
            elapsed = time.perf_counter() - start_time

            if process.returncode != 0:
                print(
                    f"[ERROR] {run_name} failed with code {process.returncode} "
                    f"after {elapsed:.1f}s",
                    flush=True,
                )
            else:
                print(f"[DONE] {run_name} finished in {elapsed:.1f}s", flush=True)

        except Exception as e:
            print(f"[EXCEPTION] {run_name}: {e}", flush=True)

print("\nBatch finished.", flush=True)
