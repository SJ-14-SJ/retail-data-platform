# Contributing

Use Python 3.12 and start with the [quick start](README.md#quick-start-no-database-server-required). Small changes with a reproducible example are easiest to review.

1. Describe the input, expected behaviour and current behaviour in an issue or pull request.
2. Work on a branch. Keep data identity and checkpoint changes explicit.
3. Run `python -m unittest discover -s tests -v`.
4. For ingestion changes, demonstrate interruption, restart and replay. For SQL changes, run the PostgreSQL/dbt path from the README. GitHub Actions also exercises both database paths.
5. Update the relevant command, result or limitation in the docs. Distinguish a synthetic measurement from a real deployment outcome.

Do not commit generated event feeds, local databases or the original UCI transaction file. Use the small deterministic fixtures in tests to reproduce bugs. Describe any AI assistance and which checks you personally ran.

The [next steps](docs/NEXT-STEPS.md) list concrete extensions. An unchecked item is proposed work, not an implemented capability.
