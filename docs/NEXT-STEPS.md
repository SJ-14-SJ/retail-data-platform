# Work to own and extend

1. Run the failure demonstration and explain why the checkpoint stays at 100.
2. Add a new optional source field and document backward-compatible handling.
3. Review the implemented streaming reader and [benchmark](BENCHMARK.md). Extend it with file identity and byte-offset checkpoints, including tests for prefix edits, truncation and restart; do not weaken replay safety.
4. Add a source watermark and tests that distinguish missing capture from genuine zero sales.
5. Add an inventory snapshot table and a freshness test.
6. Coordinate multiple writers using a tested locking strategy. Do not claim concurrency guarantees until conflict tests pass.
7. Inspect the generated dbt lineage and explain the customer retention denominator.

Suggested interview explanation: what arrives, how identities work, what is committed atomically, how retries behave, how you validate the output, and which limitations remain.
