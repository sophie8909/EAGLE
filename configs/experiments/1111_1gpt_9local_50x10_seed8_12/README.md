# 1 GPT seed + 9 local，50 代 × 5 seeds

沿用 `1108_gpt_vs_local_50x10_seed8_9/1_gpt_9_local_seed8_9.yaml` 的實驗條件，擴充為 seeds **8、9、10、11、12**，每個 seed 跑一次，population 10，演化 50 代（另有 generation 0 初始化）。

- 共用原始 `gpt_finite_rule_market_v1` framework；引用 `1104_description_guided/bundle.json` 的相同 LF bytes，避免原路徑本機 CRLF 引起 hash 不符。
- 固定 bundle SHA256：`f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b`。
- 每個 seed 的第一個初始個體使用原 config 的同一份 frozen GPT genome；其餘 9 個依 seed 取樣 local genomes，後續使用 Qwen3.5 9B local evolution。啟動時不重新呼叫 GPT。
- 五次共用 framework 與 GPT genome，但不固定整個初始 population；9 個 local genomes 隨 seed 改變。
- 保留 self-play、每 5 代更新對手、語意 probes、crossover 0.75、mutation 1.0、parent cached evaluation 與原有 selection。

## 執行（原 Ubuntu 環境，repository 根目錄）

```bash
bash experiment.sh configs/experiments/1111_1gpt_9local_50x10_seed8_12
```

批次依序執行五個 seeds，並由 orchestrator 管理 config 指定的 local llama-server。GGUF 與 llama-server 路徑沿用原本的 Ubuntu 設定；本次僅準備 config，未執行實驗。

若已手動啟動相同模型於 port 18080：

```bash
bash experiment.sh configs/experiments/1111_1gpt_9local_50x10_seed8_12 --connect-only
```

Windows 已啟動相同模型時，可在具備 EAGLE 相依套件的 Python 環境執行：

```powershell
python -m eagle experiment --config-dir configs/experiments/1111_1gpt_9local_50x10_seed8_12 --connect-only
```

中斷後續跑整批（folder 中的 experiment.yaml 由執行器產生）：

```bash
bash experiment.sh --resume configs/experiments/1111_1gpt_9local_50x10_seed8_12
```

若原本使用 `--connect-only`，續跑也加上該參數。
