# Retail Data Platform

[![Pipeline and data tests](https://github.com/SJ-14-SJ/retail-data-platform/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/SJ-14-SJ/retail-data-platform/actions/workflows/pipeline.yml)

A reproducible retail pipeline that turns versioned order events into a queryable warehouse and a daily-demand dataset. Built to demonstrate data ingestion, transactional recovery, SQL modelling and data-quality testing.

[Case study](docs/CASE-STUDY.md) · [Measured benchmark](docs/BENCHMARK.md) · [Design decisions](docs/DESIGN.md) · [Companion forecasting application](https://github.com/SJ-14-SJ/demand-forecasting-app)

## Review in two minutes

| Question | Evidence |
| --- | --- |
| What happens when ingestion fails? | Page data and checkpoint commit together; [regression tests](tests/test_pipeline.py) demonstrate rollback, restart, replay and late corrections. |
| How does the reader handle a larger file? | [Measured at 100,000 synthetic records](docs/BENCHMARK.md): peak traced Python reader allocations fell from 159.51 MiB for full-file parsing to 0.289 MiB for streaming, at 100 records/page. This is reader memory, not total process memory. |
| Can it run against a warehouse? | [GitHub Actions](https://github.com/SJ-14-SJ/retail-data-platform/actions/workflows/pipeline.yml) runs PostgreSQL ingestion tests and dbt models with data checks. |
| Where does the analytical dataset go? | 6,072 selected UCI rows produce 1,119 daily observations consumed by [DemandLab](https://github.com/SJ-14-SJ/demand-forecasting-app). |

## What you can inspect

- **Transactional pages:** accepted events, rejected-event records, dimension updates and the source checkpoint commit together.
- **Replay safety:** an event ID is processed once. Conflicting reuse fails the page instead of silently changing history.
- **Streaming file reader:** keeps pages in memory and counts nonblank records for restart; malformed JSON leaves the current page uncommitted.
- **Late updates:** a higher line revision replaces an older version, including cancellations; stale revisions cannot overwrite newer data.
- **Explicit validation:** unsupported schema versions and invalid fields are recorded as rejected events.
- **Two database paths:** SQLite for a quick local run; PostgreSQL with dbt for warehouse modelling.
- **Reviewable analytics:** dense daily demand and customer cohort retention, plus dbt uniqueness, relationship and value tests.
- **Scheduled reproducibility:** GitHub Actions runs the demo, tests SQLite and PostgreSQL, builds dbt models and retains report artifacts. Its weekly run uses a fresh demonstration database, not a persistent production warehouse.

## Quick start: no database server required

Python 3.12 is the tested version. From the repository root:

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m retail.generate_sample
python -m retail.cli ingest
python -m retail.cli export
python -m unittest discover -s tests -v
```

The generated `data/events.jsonl` is **synthetic**, reproducible with seed 42: 1,260 base sale lines over 420 days for three products, plus a late correction, cancellation, replay and invalid-schema event. There are no real customer identities in this sample. Outputs are `outputs/daily_demand.csv` and `outputs/event_quality.csv`.

Run ingestion again: the offset is already committed and no duplicate sales appear.

For a reproducible memory and ingestion experiment, run `python -m retail.benchmark`. See the [measurement protocol and raw results](docs/BENCHMARK.md).

## Demonstrate interrupted-run recovery

Use a new disposable database so earlier checkpoints do not skip the demonstration:

```bash
python -m retail.cli ingest --database-url sqlite:///recovery-demo.db --fail-page 1
# The command above intentionally fails. Run the next commands separately.
python -m retail.cli ingest --database-url sqlite:///recovery-demo.db
python -m retail.cli export --database-url sqlite:///recovery-demo.db --output outputs/recovered
```

The first 100 events commit. The second page rolls back, including its checkpoint. The next run resumes at event 100 and completes. Tests verify this behaviour and conflicting-ID rollback.

## PostgreSQL and dbt

The Compose service binds only to localhost and uses documented local-demo credentials.

```bash
docker compose up -d --wait
python -m pip install -r requirements-dbt.txt
python -m retail.cli ingest --database-url postgresql+psycopg://retail:retail@localhost:5432/retail
python -m retail.cli export --database-url postgresql+psycopg://retail:retail@localhost:5432/retail
dbt build --project-dir dbt --profiles-dir dbt
```

Core tables live in `public`; dbt models live in `analytics`. Environment variables in `.env.example` show connection configuration. The CLI reads environment variables directly; it does not automatically load `.env`.

## Local API source

In one terminal, run `python -m uvicorn retail.mock_api:app --port 8010`. In another, run:

```bash
python -m retail.cli api --database-url sqlite:///api-demo.db
```

This simulator returns the same append-only event feed through pagination. A network failure aborts the command; rerunning resumes from the last committed page. It does not claim to connect to a real retailer.

## Public dataset path

A separate importer supports [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail), attributed to Daqing Chen (2015), [DOI: 10.24432/C5BW33](https://doi.org/10.24432/C5BW33), licensed **CC BY 4.0**. Download and extract `Online Retail.xlsx` from UCI, then run:

```bash
python -m retail.prepare_uci_demo '/path/to/Online Retail.xlsx' --output outputs/uci
```

This selects the three products with the most distinct positive-sale invoices in the first 120 days, limits sales to the UK and excludes the final partial day. Selection happens before forecasting validation and holdout windows. The verified run converted **6,072 rows** into **1,119 daily product observations**. Only aggregated sales, product descriptions and provenance are shared with the companion application; customer identifiers are not published there.

For a full-file conversion: `python -m retail.import_uci '/path/to/Online Retail.xlsx' /path/to/events.jsonl`. Use a separate database/source identity for a different source snapshot.

## Architecture

```mermaid
flowchart TD
    A[Versioned file or API events] --> B[Validate each page]
    B --> C[Transactional warehouse]
    C --> D[Raw audit and checkpoint]
    C --> E[Customer and product dimensions]
    C --> F[Latest order lines]
    F --> G[dbt analytics]
    F --> H[Daily CSV export]
    H --> I[Forecasting application]
```

## Important boundaries

- One writer per source is supported. PostgreSQL locks existing checkpoint rows, but first-writer races and cross-source line contention need stronger coordination before concurrent production use.
- File ingestion expects an append-only source. Replacing or reordering previously processed contents is unsupported. Streaming bounds retained records by page size, but a resume still scans the committed prefix and individual record size is not capped.
- UCI cancellation rows are excluded from gross sales; this is **not net revenue** and not a full returns reconciliation system.
- Calendar gaps are zero-filled under an explicit complete-capture assumption. An upstream outage must not be mistaken for zero demand.
- Orders and revenue are implemented; live inventory and payment integrations are future work. No operational savings or production scale are claimed.

See [design decisions](docs/DESIGN.md), [development exercises](docs/NEXT-STEPS.md) and [contributing](CONTRIBUTING.md). Implemented with Codex assistance; use the tests and exercises to explain and extend the work.

Code is MIT-licensed. External data retains its separate CC BY 4.0 attribution.
