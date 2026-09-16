import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pandas as pd
from sqlalchemy import select, func
from retail.database import connect, order_lines
from retail.pipeline import ingest_api
from retail.import_uci import convert


class SourceTests(unittest.TestCase):
    def test_http_pagination_and_restart(self):
        row = dict(
            schema_version=1,
            event_id="e1",
            line_id="l1",
            order_id="o1",
            sku="s1",
            customer_id="c1",
            order_date="2025-01-01",
            quantity=2,
            unit_price_cents=100,
            status="sale",
            revision=1,
        )
        rows = [row, dict(row, event_id="e2", line_id="l2")]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                q = parse_qs(urlparse(self.path).query)
                start = int(q["offset"][0])
                limit = int(q["limit"][0])
                payload = json.dumps(rows[start : start + limit]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            engine = connect("sqlite:///:memory:")
            url = f"http://127.0.0.1:{server.server_port}/events"
            self.assertEqual(ingest_api(engine, url, page_size=1), 2)
            self.assertEqual(ingest_api(engine, url, page_size=1), 2)
            with engine.connect() as conn:
                self.assertEqual(
                    conn.execute(
                        select(func.count()).select_from(order_lines)
                    ).scalar(),
                    2,
                )
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_uci_conversion_retains_cancellation_and_unknown_customer(self):
        with tempfile.TemporaryDirectory() as d:
            workbook = Path(d, "input.xlsx")
            output = Path(d, "events.jsonl")
            pd.DataFrame(
                [
                    dict(
                        InvoiceNo="1",
                        StockCode="A",
                        Quantity=2,
                        InvoiceDate="2011-01-01",
                        UnitPrice=1.25,
                        CustomerID=10,
                    ),
                    dict(
                        InvoiceNo="C2",
                        StockCode="A",
                        Quantity=-2,
                        InvoiceDate="2011-01-02",
                        UnitPrice=1.25,
                        CustomerID=None,
                    ),
                ]
            ).to_excel(workbook, index=False)
            self.assertEqual(convert(workbook, output), 2)
            rows = [json.loads(x) for x in output.read_text().splitlines()]
            self.assertEqual(rows[0]["unit_price_cents"], 125)
            self.assertEqual(rows[1]["status"], "cancelled")
            self.assertEqual(rows[1]["customer_id"], "unknown")


if __name__ == "__main__":
    unittest.main()
