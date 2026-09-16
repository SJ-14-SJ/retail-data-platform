# Ingestion benchmark

Measured 2026-09-16 on Linux x86_64, Python 3.12.14. Synthetic JSONL; page size 100; three reader runs per size with alternating order. File generation is excluded. Raw observations and the pipeline source checksum are in [benchmark.json](results/benchmark.json).

## Reader memory

This compares the former full-file parsing strategy with the page iterator used by ingestion. Memory is **peak traced Python allocations**, measured with `tracemalloc`; it is not total process RSS, a container memory limit or a database memory measurement. Timing also includes tracing overhead.

| Records | Input MiB | Eager peak MiB | Streaming peak MiB | Eager median seconds | Streaming median seconds |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.21 | 1.588 | 0.288 | 0.018 | 0.017 |
| 10,000 | 2.15 | 15.906 | 0.289 | 0.195 | 0.170 |
| 100,000 | 21.82 | 159.510 | 0.289 | 2.187 | 1.675 |

At 100,000 records, the measured reader peak fell from about **159.51 MiB to 0.289 MiB**. The streaming reader retains pages rather than the complete source. Memory still depends on page size and the size of individual records. This is not a claim that the entire ingestion process uses 0.289 MiB.

## Full SQLite ingestion

A separate untraced, single-writer run ingested **10,000 synthetic events in 4.28 seconds** (about 2,335 records/second) into a fresh temporary SQLite database. The resumed run, with no new records, took 0.0023 seconds. Setup and data generation are excluded.

Verification: 10,000 order lines, 10,000 audit rows, checkpoint 10,000; rerunning added no records. This throughput measurement is one run on a shared development machine. It is not a service-level objective, PostgreSQL benchmark or result under concurrent load.

## Reproduce

```bash
python -m retail.benchmark
```

Default output: `outputs/benchmark.json`. The command creates disposable input and databases, checks every reader count and verifies database/checkpoint counts after initial ingestion and restart. Temporary data is removed automatically.

CI runs a smaller smoke experiment and uploads its result with the analytics artifact. CI validates correctness; it has no timing or memory threshold that could fail because of a busy runner.

## Trade-offs and next measurement

- Resume still scans the committed prefix, so startup work is linear in that prefix. A byte-offset checkpoint could reduce this after defining file identity and prefix validation.
- Malformed JSON aborts its page; previously committed pages remain durable. Schema-invalid but parseable events still enter the quarantine audit.
- The file must remain append-only. The reader detects truncation below the committed record count, but does not detect all same-length edits to the committed prefix.
- Benchmark source freshness, PostgreSQL load and writer coordination separately before making broader operational claims.
