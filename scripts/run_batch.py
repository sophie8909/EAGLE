import subprocess
import os
import datetime
from pathlib import Path

# ===== CONFIG =====
PYTHON_CMD = ["python", "-m", "eagle.main"]

CONFIGS_DIR = "configs/evolution/experiments/llm_interval"
# ===== SETUP =====
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_dir = Path("batch_logs") / timestamp
log_dir.mkdir(parents=True, exist_ok=True)

print(f"Batch start: {timestamp}")
print(f"Logs: {log_dir}")
print()

# ===== RUN =====
for config_file in os.listdir(CONFIGS_DIR):
    if not config_file.endswith(".json"):
        continue

    config = os.path.join(CONFIGS_DIR, config_file)
    config_path = Path(config)

    if not config_path.exists():
        print(f"[SKIP] config not found: {config}")
        continue

    config_name = config_path.stem

    run_name = f"{config_name}"
    log_file = log_dir / f"{run_name}.log"

    cmd = PYTHON_CMD + ["--config", config,]

    print("=" * 60)
    print(f"[RUN] {run_name}")
    print(f"[CMD] {' '.join(cmd)}")
    print(f"[LOG] {log_file}")
    print("=" * 60)

    with open(log_file, "w") as f:
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            for line in process.stdout:
                print(line, end="")   # terminal
                f.write(line)         # log

            process.wait()

            if process.returncode != 0:
                print(f"[ERROR] {run_name} failed with code {process.returncode}")

        except Exception as e:
            print(f"[EXCEPTION] {run_name}: {e}")

print("\nBatch finished.")