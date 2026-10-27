# Benchmark corpus

`v1/manifest.json` indexes 360 solvable and 20 unsolvable levels, with seeds,
certificates, partitions, and generation statistics. Level files are in `v1/levels/`.

Open a level with:

```sh
uv run bloxorz-solver --level benchmarks/v1/levels/unsolvable-000.json
```

Keep the v1 corpus and partitions fixed for reproducible comparisons. Generate new
corpora in a separate directory. See the [benchmark guide](../docs/benchmark.md).
