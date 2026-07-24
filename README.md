# EAGLE

EAGLE (Evolutionary Algorithm for Game-playing with LLM-Enabled Agents) evolves a three-part Candidate genotype into complete Java MicroRTS agents. NSGA-II persists canonical objective values and run artifacts for reproducible analysis.

## Run

The normal entrypoint is:

\`\`\`bash
./run.sh
\`\`\`

\`run.sh\` prepares the \`eagle\` environment, starts the GUI, and starts the GUI liveness watchdog. Use the GUI’s Servers section for local LLM lifecycle and role assignment, Experiment for configuration/prompts/execution, and Analysis for multi-objective and timing inspection.

For a deterministic local validation run without the GUI:

\`\`\`bash
python3 scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
\`\`\`

See [\`docs/architecture/EAGLE_RUNTIME.md\`](docs/architecture/EAGLE_RUNTIME.md) for ownership and artifact flow.