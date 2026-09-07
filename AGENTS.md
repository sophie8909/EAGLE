# Repository agent guidance

## Codex usage budget

Run `scripts/codex-budget` before substantial work, after a major milestone in a long-running task, and before starting another expensive phase. Do not poll it after trivial commands.

Use its effective mode to control scope:

- `AGGRESSIVE`: broad repository work, comprehensive validation, and directly related high-value cleanup are allowed.
- `NORMAL`: complete the requested scope with appropriate inspection and tests.
- `CONSERVATIVE`: focus on required work and targeted validation; avoid speculative refactors, unrelated cleanup, duplicate validation, and broad exploration.
- `CRITICAL`: complete only the highest-value small milestone that makes concrete progress.
- `STOP`: do not start substantial new work; cheaply inspect or summarize existing changes and leave clear continuation instructions.
- `UNKNOWN`: proceed cautiously and do not assume quota is unlimited.

For substantial tasks, order work as independently useful milestones: inspect, implement core behavior, run targeted validation, make secondary improvements, then run broad validation. Re-read the budget before another expensive milestone. If the mode degrades, reduce remaining scope, but always leave the repository coherent and never intentionally leave it broken.

## Long-running experiments

When the user asks to execute an experiment:

- Prefer the existing user-visible VS Code terminal when it is accessible. If the environment cannot control that exact terminal, use a persistent local PTY and state that limitation.
- Start the experiment and retain its terminal session and run-directory identifiers. Do not continuously stream or analyze routine progress output.
- Check the process approximately once per hour. Check sooner only when the process reports completion, failure, or a request for user input.
- When the experiment finishes, report the result in the originating task so the Codex/ChatGPT mobile app can deliver its normal completion notification. Remind the user to enable mobile notifications if delivery is not configured.
- Create monitoring only after a concrete experiment has started; do not leave a generic idle monitor running between experiments.
