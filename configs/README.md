# EAGLE configurations

This directory contains the small set of configurations intended to remain
runnable from the current checkout.

- `experiments/` contains active experiment inputs and `experiment.yaml` batch
  indexes. Index files record local run directories and are not portable
  between machines.
- `framework_bundles/` contains frozen, hash-pinned framework materialization
  bundles used by framework-slot experiments.

Historical experiment inputs remain available through experiment reports and
Git history rather than alongside the active configuration set. Tests that
need a specific configuration contract construct a minimal configuration in a
temporary directory, so removing an obsolete experiment does not remove
coverage from the configuration parser.

Local model paths and credentials belong outside version control. The
repository ignores `api_key/`, local model assets, and generated run outputs.
