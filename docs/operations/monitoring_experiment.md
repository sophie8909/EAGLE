# Monitoring local EAGLE experiments

EAGLE includes a read-only resident status agent for the experiment host. Start
one agent against the `runs/` root; it discovers every direct child containing a
canonical `eagle-run-v2` `manifest.json`, including runs created later by
`python -m eagle experiment`. It reads the latest atomic `generation_*.json`; it
does not parse terminal output and it cannot start, stop, or modify an
experiment.

## Start the agent

Start one resident agent for all current and future runs:

```bash
python -m eagle monitor \
  --runs-root runs \
  --host 0.0.0.0 \
  --port 8765
```

For a local-only agent, loopback does not need a token:

```bash
python -m eagle monitor --runs-root runs --host 127.0.0.1 --port 8765
```

Token protection is optional. Restrict the port in the host firewall to the
monitor computer or VPN address, especially when no token is configured. The
API is read-only; `POST` requests are rejected. Keep this process running as a systemd service,
tmux session, or equivalent resident process.

To inspect one run instead of the whole root, use `--run-dir runs/<run_id>`.
The optional `--pid` flag is available only in this single-run mode.

Use `--once` to validate the run and inspect one snapshot without opening a
server:

```bash
python -m eagle monitor --runs-root runs --once
```

## Endpoints

- `GET /health` is an unauthenticated liveness check.
- `GET /status` returns the detailed `eagle-monitor-status-v1` payload with all discovered runs.
- `GET /status.json` returns the compact `eagle-monitor-summary-v1` payload for consumers that only need run/generation/PID state.
- `GET /status/<run_id>` returns one discovered run.
- `GET /runs` is an alias for the detailed `/status` payload.
- When a token is configured, send `Authorization: Bearer <shared-secret>`;
  without a token, the JSON URL can be opened directly in a browser.

For direct browser navigation, the token may also be supplied as a URL query:

```text
http://<experiment-host>:8765/status.json?token=<shared-secret>
```

This is convenient but less safe: the token can remain in browser history,
bookmarks, proxy logs, or copied URLs. Prefer the Authorization header for
long-term use.

The detailed status includes host CPU load, memory, disk, NVIDIA GPU telemetry
when `nvidia-smi` is available, the run status and latest generation, match
progress, fitness summaries, opponent summaries, AOS state, bounded
error-memory records, and the experiment PID. A running or initialized run is
marked `stale` when its manifest update is older than `--stale-after` seconds
(180 by default).

The compact `/status.json` response and `runs/monitor_status.json` contain
`total_runs`, configured `total_generations`, `current_run_id`,
`current_generation`, `current_pid`, `current_alive`, and `current_status`,
plus one small entry per run. Normal completion is reported as `complete`.
If an active run's recorded PID no longer exists, it is reported as
`unexpected_termination`; Ctrl-C and handled exceptions remain
`interrupted` and `failed` respectively.
If no run has a live PID (including an empty runs root or a legacy manifest
without a PID), the overall current status is `complete` and
`current_alive` is `false`.

The resident process also atomically updates `runs/monitor_status.json` every
30 seconds by default. Change the destination or interval with:

```bash
python -m eagle monitor \
  --runs-root runs \
  --snapshot-file /var/lib/eagle/monitor_status.json \
  --snapshot-interval 10
```

The JSON file is derived monitoring output, not a canonical EAGLE run artifact.

The monitor only reports the latest atomically recorded generation. A partially
written candidate or console line is not treated as completed evidence.
