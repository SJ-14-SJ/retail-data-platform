# From retail events to an auditable warehouse

## Problem

A source can deliver the same sale twice, correct it later or stop halfway through a batch. Counting deliveries as sales would make demand and revenue unreliable. This project explores how to preserve a recoverable audit trail while exposing the latest valid order state to analytics.

The scope is deliberately inspectable: an append-only JSONL/API source, Python ingestion, SQLite/PostgreSQL storage, dbt models and a daily dataset for a forecasting application. The local API is a simulator. A separate attributed importer supports UCI Online Retail.

## Decisions and evidence

| Decision | Why | Where to inspect |
| --- | --- | --- |
| Separate event IDs from order-line IDs | Distinguish a replay from a new correction to an existing sale. | [`process_page`](../retail/pipeline.py) and replay/revision tests |
| Commit a page and its checkpoint in one transaction | A crash cannot advance the offset past uncommitted sales. | Failure injection and restart test in [`test_pipeline.py`](../tests/test_pipeline.py) |
| Quarantine invalid schemas; fail conflicting identities | Invalid input stays inspectable, while contradictory history is not silently accepted. | `raw_events.outcome` and `reason`; conflict rollback tests |
| Use integer cents | Avoid binary floating-point accumulation in stored line prices. | [`database.py`](../retail/database.py) and SQL models |
| Keep transformations in dbt | SQL dependencies and analytics checks stay separate from ingestion control flow. | [`dbt/models`](../dbt/models) and [`dbt/tests`](../dbt/tests) |
| Stream the file by page | Larger files need not be retained in memory in full. | [`benchmark.py`](../retail/benchmark.py) and [measured results](BENCHMARK.md) |

## Measured outcome

The reader benchmark covers 1,000, 10,000 and 100,000 synthetic records with three runs per size. At 100,000 records, peak traced Python allocations dropped from 159.51 MiB for the eager reference to 0.289 MiB for the streaming reader. This measures the reader only; database and total process memory are outside that number.

A separate fresh SQLite run processed 10,000 synthetic events in about 4.28 seconds. Row counts and checkpoint matched the input, and a resumed run added no duplicates. See the raw measurements and limitations before comparing throughput across systems.

The public-data path transforms 6,072 selected UCI rows into 1,119 daily observations, with product selection restricted to an early historical window. [DemandLab](https://github.com/SJ-14-SJ/demand-forecasting-app) consumes those aggregates and retains source attribution. This is a portfolio experiment, not a retailer deployment or measured business saving.

## Failure walkthrough

1. Generate the synthetic source using the README quick start.
2. Run the documented `--fail-page 1` demonstration against a new database.
3. Check that the first page committed and the second page did not advance its checkpoint.
4. Restart and export; compare row counts with an uninterrupted run.
5. Read the regression tests for conflicting IDs, stale revisions, blank lines, truncation and malformed JSON.

## Next engineering decision

The current reader still scans committed records on restart and assumes an immutable prefix. The next step is a tested source identity/byte-offset design. Separately, production concurrency needs coordination for initial checkpoints and cross-source line conflicts. Neither guarantee is claimed by the current implementation.

Implemented with Codex assistance. The commit history, reproducible commands and explicit limitations make the work reviewable; the [development exercises](NEXT-STEPS.md) identify the parts to understand and extend.
