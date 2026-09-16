"""Seeded synthetic data; no real customers or measured business outcomes."""

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path


def generate(path, days=420, seed=42):
    rng = random.Random(seed)
    rows = []
    for day in range(days):
        for index, (sku, base, price) in enumerate(
            [("MUG-01", 24, 1299), ("BAG-02", 16, 2499), ("LAMP-03", 10, 3999)]
        ):
            current = date(2024, 1, 1) + timedelta(days=day)
            weekly = [0.8, 0.85, 0.9, 1.0, 1.2, 1.4, 1.1][current.weekday()]
            units = max(
                0, round(base * weekly * (1 + 0.0009 * day) + rng.gauss(0, 2.5))
            )
            identifier = f"{day:04}-{index}"
            rows.append(
                dict(
                    schema_version=1,
                    event_id="e-" + identifier,
                    line_id="l-" + identifier,
                    order_id="o-" + identifier,
                    sku=sku,
                    customer_id=f"customer-{rng.randrange(80):03}",
                    order_date=current.isoformat(),
                    quantity=units,
                    unit_price_cents=price,
                    status="sale",
                    revision=1,
                )
            )
    # A late correction, a cancellation, a replay and an invalid schema illustrate operations.
    correction = dict(
        rows[10],
        event_id="late-correction",
        revision=2,
        quantity=rows[10]["quantity"] + 3,
    )
    cancellation = dict(
        rows[20], event_id="late-cancellation", revision=2, status="cancelled"
    )
    rows.extend(
        [
            correction,
            cancellation,
            dict(rows[0]),
            dict(rows[1], event_id="bad-schema", schema_version=2),
        ]
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    return len(rows)


if __name__ == "__main__":
    print("Synthetic event records:", generate("data/events.jsonl"))
