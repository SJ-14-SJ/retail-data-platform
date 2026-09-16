import argparse
import logging
import os
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from .database import connect
from .pipeline import ingest_file, ingest_api


def export(engine, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        sales = pd.read_sql(
            text(
                "SELECT sku, order_date AS date, SUM(quantity) AS units, SUM(quantity * unit_price_cents) AS revenue_cents FROM order_lines WHERE status = 'sale' GROUP BY sku, order_date ORDER BY sku, order_date"
            ),
            conn,
        )
        bounds = conn.execute(
            text("SELECT MIN(order_date), MAX(order_date) FROM order_lines")
        ).one()
        quality = pd.read_sql(
            text("SELECT outcome, COUNT(*) AS events FROM raw_events GROUP BY outcome"),
            conn,
        )
    if sales.empty:
        raise ValueError("No sales available to export")
    sales["date"] = pd.to_datetime(sales["date"])
    grid = pd.MultiIndex.from_product(
        [sorted(sales.sku.unique()), pd.date_range(bounds[0], bounds[1])],
        names=["sku", "date"],
    )
    dense = sales.set_index(["sku", "date"]).reindex(grid, fill_value=0).reset_index()
    dense["date"] = dense["date"].dt.strftime("%Y-%m-%d")
    dense.to_csv(output / "daily_demand.csv", index=False)
    quality.to_csv(output / "event_quality.csv", index=False)
    return len(dense)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest", "export", "api"])
    parser.add_argument(
        "--database-url", default=os.getenv("DATABASE_URL", "sqlite:///retail.db")
    )
    parser.add_argument("--input", default="data/events.jsonl")
    parser.add_argument("--url", default="http://127.0.0.1:8010/events")
    parser.add_argument("--output", default="outputs")
    parser.add_argument("--fail-page", type=int)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    engine = connect(args.database_url)
    if args.command == "ingest":
        print(
            "Source offset:", ingest_file(engine, args.input, fail_page=args.fail_page)
        )
    elif args.command == "api":
        print("Source offset:", ingest_api(engine, args.url))
    else:
        print("Daily rows:", export(engine, args.output))


if __name__ == "__main__":
    main()
