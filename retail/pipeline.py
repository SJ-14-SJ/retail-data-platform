"""Pages commit atomically with their checkpoint; replay never duplicates a sale."""

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from sqlalchemy import select, insert, update
from .database import raw_events, products, customers, order_lines, checkpoints

logger = logging.getLogger(__name__)
REQUIRED = {
    "schema_version",
    "event_id",
    "line_id",
    "order_id",
    "sku",
    "customer_id",
    "order_date",
    "quantity",
    "unit_price_cents",
    "status",
    "revision",
}


def validate(event):
    if not isinstance(event, dict):
        raise ValueError("Event must be an object")
    missing = REQUIRED - event.keys()
    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("Unsupported schema_version")
    for key in ["event_id", "line_id", "order_id", "sku", "customer_id"]:
        if not isinstance(event[key], str) or not 0 < len(event[key]) <= 100:
            raise ValueError(
                f"{key} must be a nonempty string of at most 100 characters"
            )
    if date.fromisoformat(event["order_date"]).isoformat() != event["order_date"]:
        raise ValueError("order_date must use YYYY-MM-DD")
    for key in ["quantity", "unit_price_cents", "revision"]:
        if type(event[key]) is not int or event[key] < (1 if key == "revision" else 0):
            raise ValueError(f"Invalid {key}")
    if event["status"] not in ["sale", "cancelled"]:
        raise ValueError("Unknown order status")


def checkpoint(engine, source):
    with engine.connect() as conn:
        return (
            conn.execute(
                select(checkpoints.c.offset).where(checkpoints.c.source == source)
            ).scalar_one_or_none()
            or 0
        )


def process_page(engine, events, source, offset, fail_before_checkpoint=False):
    """One writer per source. Unexpected failures roll back the complete page."""
    counts = dict(applied=0, replayed=0, stale=0, rejected=0)
    with engine.begin() as conn:
        current = conn.execute(
            select(checkpoints.c.offset)
            .where(checkpoints.c.source == source)
            .with_for_update()
        ).scalar_one_or_none()
        if (current or 0) != offset:
            raise ValueError("Stale checkpoint: another worker advanced this source")
        for event in events:
            payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
            event_id = event.get("event_id") if isinstance(event, dict) else None
            if not isinstance(event_id, str) or not 0 < len(event_id) <= 100:
                event_id = "invalid-" + hashlib.sha256(payload.encode()).hexdigest()
            existing = conn.execute(
                select(raw_events.c.payload).where(raw_events.c.event_id == event_id)
            ).scalar_one_or_none()
            if existing is not None:
                if existing != payload:
                    raise ValueError("An event_id was reused with different content")
                counts["replayed"] += 1
                continue
            try:
                validate(event)
            except (ValueError, TypeError) as exc:
                conn.execute(
                    insert(raw_events).values(
                        event_id=event_id,
                        payload=payload,
                        outcome="rejected",
                        reason=str(exc),
                    )
                )
                counts["rejected"] += 1
                continue
            previous = (
                conn.execute(
                    select(order_lines).where(order_lines.c.line_id == event["line_id"])
                )
                .mappings()
                .first()
            )
            values = {col.name: event[col.name] for col in order_lines.columns}
            if previous and event["revision"] <= previous["revision"]:
                if event["revision"] == previous["revision"] and any(
                    previous[k] != v for k, v in values.items()
                ):
                    raise ValueError("Conflicting payload at the same line revision")
                outcome = "stale"
            else:
                for table, key in [(products, "sku"), (customers, "customer_id")]:
                    if (
                        conn.execute(
                            select(table.c[key]).where(table.c[key] == event[key])
                        ).first()
                        is None
                    ):
                        conn.execute(insert(table).values(**{key: event[key]}))
                if previous:
                    conn.execute(
                        update(order_lines)
                        .where(order_lines.c.line_id == event["line_id"])
                        .values(**values)
                    )
                else:
                    conn.execute(insert(order_lines).values(**values))
                outcome = "applied"
            conn.execute(
                insert(raw_events).values(
                    event_id=event_id, payload=payload, outcome=outcome
                )
            )
            counts[outcome] += 1
        if fail_before_checkpoint:
            raise RuntimeError("Simulated failure before checkpoint commit")
        new_offset = offset + len(events)
        if current is None:
            conn.execute(insert(checkpoints).values(source=source, offset=new_offset))
        else:
            conn.execute(
                update(checkpoints)
                .where(checkpoints.c.source == source)
                .values(offset=new_offset)
            )
    logger.info(
        "page_committed source=%s offset=%s counts=%s", source, new_offset, counts
    )
    return counts


def iter_file_pages(path, start=0, page_size=100):
    """Read at most a page of nonblank JSONL records into memory.

    Checkpoints count records, not physical lines or bytes. Resuming scans the
    committed prefix without parsing it; callers must keep that prefix immutable.
    A syntax error prevents its entire page from being yielded.
    """
    if page_size < 1:
        raise ValueError("page_size must be positive")
    if start < 0:
        raise ValueError("start must be nonnegative")
    seen = 0
    page = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            if seen < start:
                seen += 1
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at line {line_number}; current page was not committed"
                ) from exc
            page.append(event)
            seen += 1
            if len(page) == page_size:
                yield page
                page = []
    if seen < start:
        raise ValueError("Source was truncated; use a new source identity")
    if page:
        yield page


def ingest_file(engine, path, page_size=100, source=None, fail_page=None):
    source = source or str(Path(path).resolve())
    offset = checkpoint(engine, source)
    for pages, page in enumerate(iter_file_pages(path, offset, page_size)):
        process_page(
            engine, page, source, offset, fail_before_checkpoint=(pages == fail_page)
        )
        offset += len(page)
    return offset


def ingest_api(engine, base_url, page_size=100):
    """Read an append-only paginated event API. Restart the command to resume."""
    source = base_url
    offset = checkpoint(engine, source)
    while True:
        with urlopen(
            base_url + "?" + urlencode({"offset": offset, "limit": page_size}),
            timeout=15,
        ) as response:
            page = json.load(response)
        if not isinstance(page, list):
            raise ValueError("API must return an array of events")
        if not page:
            return offset
        process_page(engine, page, source, offset)
        offset += len(page)
