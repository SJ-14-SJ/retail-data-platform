"""Convert UCI Online Retail to immutable line events; retain attribution."""

import argparse
import json
from pathlib import Path
import pandas as pd


def convert(xlsx, destination):
    frame = pd.read_excel(xlsx)
    expected = {
        "InvoiceNo",
        "StockCode",
        "Quantity",
        "InvoiceDate",
        "UnitPrice",
        "CustomerID",
    }
    if not expected.issubset(frame.columns):
        raise ValueError(
            f"Missing UCI columns: {sorted(expected - set(frame.columns))}"
        )
    count = 0
    with Path(destination).open("w") as handle:
        for index, row in frame.iterrows():
            if (
                pd.isna(row.InvoiceDate)
                or pd.isna(row.Quantity)
                or pd.isna(row.UnitPrice)
                or row.UnitPrice < 0
            ):
                continue
            cancelled = str(row.InvoiceNo).lower().startswith("c") or row.Quantity < 0
            event = dict(
                schema_version=1,
                event_id=f"uci-row-{index}",
                line_id=f"uci-line-{index}",
                order_id=str(row.InvoiceNo),
                sku=str(row.StockCode),
                customer_id="unknown"
                if pd.isna(row.CustomerID)
                else str(int(row.CustomerID)),
                order_date=pd.Timestamp(row.InvoiceDate).date().isoformat(),
                quantity=abs(int(row.Quantity)),
                unit_price_cents=int(round(float(row.UnitPrice) * 100)),
                status="cancelled" if cancelled else "sale",
                revision=1,
            )
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("xlsx")
    parser.add_argument("output")
    args = parser.parse_args()
    print("Converted event rows:", convert(args.xlsx, args.output))
