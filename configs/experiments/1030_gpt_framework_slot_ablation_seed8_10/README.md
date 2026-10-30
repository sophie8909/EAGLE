# GPT framework slot-selection ablation

All three treatments use the same immutable GPT-generated framework bundle.
This isolates slot initialization/evolution from framework-design variance.

1. `01_gpt_framework_gpt_slot_once.yaml`: one direct-GPT genome at generation
   zero from one provider request; benchmark generation 0 only.
2. `02_gpt_framework_local_evolution.yaml`: ten locally sampled generation-zero
   genomes and ordinary local evolution, with seeds 8, 9, and 10.
3. `03_gpt_framework_gpt_seed_local_evolution.yaml`: one direct-GPT genome plus
   nine locally sampled genomes in generation zero, followed by the same local
   evolution, with seeds 8, 9, and 10. Each seed makes exactly one direct-GPT
   selection request.

Start the folder batch without the automatic terminal-generation final test:

```bash
./experiment.sh configs/experiments/1030_gpt_framework_slot_ablation_seed8_10 --skip-final-test
```

The launcher writes each run directory to `experiment.yaml`. After a run is
complete, execute one fixed-evaluation command for all requested checkpoints:

```bash
# Treatment 1
conda run --no-capture-output -n eagle python -m eagle.fixed_evaluation \
  --run-dir runs/<treatment-1-run> --generations 0

# Each run from treatments 2 and 3
conda run --no-capture-output -n eagle python -m eagle.fixed_evaluation \
  --run-dir runs/<run> --generations 20 30 40 50 75 100
```

Each six-checkpoint command writes one combined comparison under the run's
`fixed_evaluation/` directory; it does not create six evolutionary runs.
Direct GPT calls read `api_key/gpt`; credentials are not stored in configs or
run artifacts.
