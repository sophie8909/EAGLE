Evaluation configs live here.

Current active file:

- `surrogate_validation.json`: the default base config used by `python -m scripts.run_surrogate_validation`
- `final_test.json`: the replay/final-test override used by `python -m scripts.run_prompt_eval`
  and by final benchmark replays after EA runs

You can override it with:

```bash
python -m scripts.run_surrogate_validation --config configs/evaluation/surrogate_validation.json
python -m scripts.run_prompt_eval --config configs/evaluation/final_test.json --log-dir logs/eagle/<run_dir> --generation 1
```
