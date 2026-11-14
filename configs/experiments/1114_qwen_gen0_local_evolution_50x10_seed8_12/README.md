# Gen0 Qwen + local evolution，50 代 × 5 seeds

這個 treatment 只在 generation 0 用 Qwen3.5 9B 對十個初始 genome 做一次選擇。`framework.evolution_mode: local` 會讓 generation 1–50 只走 seeded local crossover、slot mutation 與既有 survivor selection；不會執行 framework reflection、Coach offspring 或 Qwen selection。

設定為 seeds **8、9、10、11、12**、population 10、50 generations。`generations: 50` 表示 gen0 初始化加上 G1–G50 演化。

```bash
bash experiment.sh configs/experiments/1114_qwen_gen0_local_evolution_50x10_seed8_12
```

若 Qwen server 已在 port 18080 執行，可加 `--connect-only`。
