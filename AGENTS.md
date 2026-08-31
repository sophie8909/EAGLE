# Repository agent guidance

## Codex usage budget

Run `scripts/codex-budget` before substantial work, after a major milestone in a long-running task, and before starting another expensive phase. Do not poll it after trivial commands.

The weekly hard reserve is dynamic: preserve `12% * days_until_reset` of the weekly allowance, including fractional days. It is not a fixed 12% reserve.

This policy is user-overridable. If the user explicitly says to ignore, bypass, or disable usage or quota controls, stop reading and applying the budget mode for the rest of that task. Resume only when the user explicitly asks to restore the controls.

The controller also has a persistent switch: run `scripts/codex-budget off`, `on`, or `toggle`. When it reports `controller.enabled: false` and mode `UNLIMITED`, do not read or apply telemetry until it is enabled again. `UNLIMITED` means the controller is manually disabled; it does not mean the Codex account has no service limits.

Use its effective mode to control scope:

- `AGGRESSIVE`: broad repository work, comprehensive validation, and directly related high-value cleanup are allowed.
- `NORMAL`: complete the requested scope with appropriate inspection and tests.
- `CONSERVATIVE`: focus on required work and targeted validation; avoid speculative refactors, unrelated cleanup, duplicate validation, and broad exploration.
- `CRITICAL`: complete only the highest-value small milestone that makes concrete progress.
- `STOP`: do not start substantial new work; cheaply inspect or summarize existing changes and leave clear continuation instructions.
- `UNKNOWN`: proceed cautiously and do not assume quota is unlimited.
- `UNLIMITED`: the user has disabled the controller; perform the requested scope normally without budget-based downgrades.

For substantial tasks, order work as independently useful milestones: inspect, implement core behavior, run targeted validation, make secondary improvements, then run broad validation. Re-read the budget before another expensive milestone. If the mode degrades, reduce remaining scope, but always leave the repository coherent and never intentionally leave it broken.
