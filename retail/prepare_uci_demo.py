"""Reproduce an attributed forecast dataset without publishing customer IDs."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
import pandas as pd
from .import_uci import convert
from .database import connect
from .pipeline import ingest_file
from .cli import export


def prepare(workbook, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frame = pd.read_excel(workbook)
    frame["InvoiceDate"] = pd.to_datetime(frame.InvoiceDate)
    first = frame.InvoiceDate.min().normalize()
    cutoff = first + pd.Timedelta(days=120)
    last = frame.InvoiceDate.max().normalize() - pd.Timedelta(days=1)
    valid = frame[
        (frame.Country == "United Kingdom")
        & (frame.Quantity > 0)
        & (frame.UnitPrice > 0)
        & (~frame.InvoiceNo.astype(str).str.lower().str.startswith("c"))
    ]
    # Use early history only; validation and holdout never select SKUs.
    counts = valid[valid.InvoiceDate < cutoff].groupby("StockCode").InvoiceNo.nunique()
    skus = (
        counts.sort_values(ascending=False, kind="stable")
        .head(3)
        .index.astype(str)
        .tolist()
    )
    subset = frame[
        (frame.Country == "United Kingdom")
        & frame.StockCode.astype(str).isin(skus)
        & (frame.InvoiceDate < last + pd.Timedelta(days=1))
    ].copy()
    with tempfile.TemporaryDirectory() as d:
        selected = Path(d, "selected.xlsx")
        events = Path(d, "events.jsonl")
        subset.to_excel(selected, index=False)
        count = convert(selected, events)
        engine = connect("sqlite:///" + str(Path(d, "warehouse.db")))
        ingest_file(engine, events)
        rows = export(engine, output)
        engine.dispose()
    manifest = {
        "source": "UCI Online Retail",
        "author": "Daqing Chen",
        "year": 2015,
        "doi": "https://doi.org/10.24432/C5BW33",
        "license": "CC BY 4.0",
        "source_sha256": hashlib.sha256(Path(workbook).read_bytes()).hexdigest(),
        "raw_rows": len(frame),
        "converted_rows": count,
        "daily_rows": rows,
        "country": "United Kingdom",
        "selection": "Top three by distinct positive-sale invoices in first 120 calendar days",
        "selection_cutoff_exclusive": str(cutoff.date()),
        "last_complete_day": str(last.date()),
        "skus": skus,
        "descriptions": {
            sku: str(
                subset[subset.StockCode.astype(str) == sku].Description.dropna().iloc[0]
            )
            for sku in skus
        },
        "semantics": "Gross recorded sale quantities; cancellation rows excluded, not net demand after returns. Missing calendar days are zero-filled under complete-capture assumption. Final partially observed day excluded.",
    }
    (output / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("workbook")
    p.add_argument("--output", default="outputs/uci")
    a = p.parse_args()
    prepare(a.workbook, a.output)
