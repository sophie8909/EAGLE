"""Smoke-check canonical EAGLE config resolution and run-folder persistence."""

from __future__ import annotations

import tempfile
from pathlib import Path

from eagle.config import (
    RESOLVED_CONFIG_FILENAME,
    load_config_from_json,
    load_config_payload,
    resolve_config,
    resolve_config_path,
    save_resolved_config,
    select_config_path,
)


def main() -> int:
    config = resolve_config(load_config_payload({}))
    component_path = resolve_config_path(config.component_pool_path)
    if not component_path.exists():
        raise FileNotFoundError(f"Component pool not found: {component_path}")

    with tempfile.TemporaryDirectory(prefix="eagle_config_check_") as temp_dir:
        run_dir = Path(temp_dir)
        saved_path = save_resolved_config(config, run_dir)
        if saved_path.name != RESOLVED_CONFIG_FILENAME:
            raise RuntimeError(f"Unexpected resolved config path: {saved_path}")
        if select_config_path(run_dir) != saved_path:
            raise RuntimeError("Run directory did not prefer the resolved config.")
        reloaded = load_config_from_json(run_dir)

    print(
        "config ok "
        f"algorithm={reloaded.algorithm} "
        f"eval_mode={reloaded.eval_mode} "
        f"component_pool={reloaded.component_pool_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
