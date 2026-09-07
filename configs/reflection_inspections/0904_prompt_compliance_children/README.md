# Prompt Compliance chained inspection

This inspection evaluates the checked-in Worker Rush parent once, then runs
three independent Strategy Reflection trials and three independent Code
Reflection trials. Every successfully changed child becomes the input to one
Prompt Compliance Reflection trial. Failed upstream mutations remain preserved
for review but are not reused as unchanged Compliance parents.

Run the deterministic contract check:

```bash
./reflection_inspection.sh \
  configs/reflection_inspections/0904_prompt_compliance_children/inspection.yaml \
  --mock
```

Run the real Ministral inspection:

```bash
./reflection_inspection.sh \
  configs/reflection_inspections/0904_prompt_compliance_children/inspection.yaml
```

The generated `summary.md` identifies each Compliance trial's Strategy or Code
source trial. Its `trial_summary.json` also records the source artifact and the
input/output genotype hashes so the handoff can be audited without inferring
provenance from prompt text.
