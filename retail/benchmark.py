"""Reproducible reader-memory and single-writer SQLite experiments.

Synthetic inputs are generated outside the measurements. The eager reference
reproduces the former full-file reader. tracemalloc measures Python allocations,
not process RSS or database memory. There are deliberately no speed pass/fail gates.
"""

import argparse
import gc
import hashlib
import json
import platform
import statistics
import tempfile
import time
import tracemalloc
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from .database import connect, order_lines, raw_events
from .pipeline import checkpoint, ingest_file, iter_file_pages


def write_fixture(path, records):
    with Path(path).open("w", encoding="utf-8") as handle:
        for index in range(records):
            event = {
                "schema_version": 1,
                "event_id": f"event-{index}",
                "line_id": f"line-{index}",
                "order_id": f"order-{index}",
                "sku": f"sku-{index % 25}",
                "customer_id": f"synthetic-{index % 80}",
                "order_date": (date(2024, 1, 1) + timedelta(days=index % 365)).isoformat(),
                "quantity": 1 + index % 20,
                "unit_price_cents": 100 + index % 1000,
                "status": "sale",
                "revision": 1,
            }
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")


def eager_reference(path, page_size):
    events = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for start in range(0, len(events), page_size):
        yield events[start : start + page_size]


def measure_reader(reader, path, page_size):
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    count = sum(len(page) for page in reader(path, page_size))
    seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"records": count, "seconds": seconds, "peak_python_bytes": peak}


def streaming_reader(path, page_size):
    return iter_file_pages(path, page_size=page_size)


def run(sizes, repeats, page_size, pipeline_records):
    if not sizes or min(*sizes, repeats, page_size, pipeline_records) < 1:
        raise ValueError("Sizes, repeats, page size and pipeline records must be positive")
    result = {
        "schema_version": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "page_size": page_size,
        "repeats": repeats,
        "pipeline_sha256": hashlib.sha256(
            Path(__file__).with_name("pipeline.py").read_bytes()
        ).hexdigest(),
        "measurement_note": "Reader-only peak traced Python allocations; not RSS. Local synthetic workload, not a production capacity claim.",
        "readers": [],
    }
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary, "events.jsonl")
        for records in sizes:
            write_fixture(path, records)
            samples = {"eager_reference": [], "streaming": []}
            readers = [("eager_reference", eager_reference), ("streaming", streaming_reader)]
            for repetition in range(repeats):
                # Alternate order to reduce a fixed cache/order advantage.
                for name, reader in readers[:: -1 if repetition % 2 else 1]:
                    sample = measure_reader(reader, path, page_size)
                    if sample["records"] != records:
                        raise AssertionError("Reader lost records")
                    samples[name].append(sample)
            for name, runs in samples.items():
                result["readers"].append(
                    {
                        "records": records,
                        "input_bytes": path.stat().st_size,
                        "reader": name,
                        "median_seconds": statistics.median(s["seconds"] for s in runs),
                        "median_peak_python_bytes": statistics.median(
                            s["peak_python_bytes"] for s in runs
                        ),
                        "samples": runs,
                    }
                )
        write_fixture(path, pipeline_records)
        engine = connect(f"sqlite:///{Path(temporary, 'benchmark.db')}")
        try:
            started = time.perf_counter()
            offset = ingest_file(engine, path, page_size=page_size, source="benchmark")
            initial_seconds = time.perf_counter() - started
            started = time.perf_counter()
            resumed = ingest_file(engine, path, page_size=page_size, source="benchmark")
            resume_seconds = time.perf_counter() - started
            with engine.connect() as connection:
                lines = connection.execute(select(func.count()).select_from(order_lines)).scalar_one()
                audited = connection.execute(select(func.count()).select_from(raw_events)).scalar_one()
            if not (offset == resumed == lines == audited == checkpoint(engine, "benchmark") == pipeline_records):
                raise AssertionError("Row counts or checkpoint changed unexpectedly")
            result["sqlite"] = {
                "records": pipeline_records,
                "initial_ingest_seconds": initial_seconds,
                "records_per_second": pipeline_records / initial_seconds,
                "resume_no_new_records_seconds": resume_seconds,
                "order_lines": lines,
                "audit_rows": audited,
                "checkpoint": offset,
                "verification": "Exact row counts; second run adds no records",
            }
        finally:
            engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--pipeline-records", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path("outputs/benchmark.json"))
    args = parser.parse_args()
    result = run(args.sizes, args.repeats, args.page_size, args.pipeline_records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}; row-count and restart checks passed")


if __name__ == "__main__":
    main()
