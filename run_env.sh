#!/usr/bin/env bash
set -euo pipefail

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
COMMAND="${1:-start}"
[[ $# -le 1 ]] || { echo "ERROR: run_env.sh accepts one command." >&2; exit 2; }
case "$COMMAND" in start|stop|restart|status|check) ;; *) echo "ERROR: unknown command: $COMMAND" >&2; exit 2 ;; esac

exec conda run --no-capture-output -n eagle \
  python -m eagle runtime "$COMMAND" --config configs/runtime.yaml
