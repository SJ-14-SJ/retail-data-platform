"""A local source simulator. It does not connect to an actual retailer."""

import json
from pathlib import Path
from fastapi import FastAPI, Query

app = FastAPI(title="Retail event source simulator")
PATH = Path(__file__).resolve().parents[1] / "data/events.jsonl"


@app.get("/events")
def events(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    rows = [json.loads(line) for line in PATH.read_text().splitlines() if line.strip()]
    return rows[offset : offset + limit]
