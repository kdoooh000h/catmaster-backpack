# Cat Master Toolkit V1 Final Benchmark

Date: 2026-04-25

Fixture: `benchmarks/accuracy-fixture/`

| Metric | Cat Master Toolkit V1 | Full tools |
| --- | ---: | ---: |
| Correct answers | 3/3 | 3/3 |
| Initial visible tools | 1 | 27 |
| Loaded tools | 6 | 27 |
| Irrelevant tools | 0/3 | 0/3 |
| API calls | 9 | 6 |
| Prompt tokens | 8,783 | 67,472 |
| Completion tokens | 367 | 140 |
| Total tokens | 9,150 | 67,612 |
| Avg init time | 40.53 ms | 215.01 ms |
| Avg total time | 5,818.54 ms | 14,834.10 ms |

Tool call pattern:

```text
Cat Master Toolkit V1: tool_repo -> search_files
Full tools:            search_files
```

Verification:

```text
benchmark_verified rows=6 all_correct=true
```
