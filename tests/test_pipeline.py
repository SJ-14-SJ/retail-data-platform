import json
import os
import uuid
import tempfile
import unittest
from pathlib import Path
from sqlalchemy import select, func, text, create_engine
from retail.database import connect, order_lines, raw_events, metadata
from retail.pipeline import process_page, checkpoint, ingest_file
from retail.cli import export


def event(**changes):
    return dict(
        dict(
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
        ),
        **changes,
    )


class PipelineTests(unittest.TestCase):
    def setUp(self):
        url = os.getenv("TEST_DATABASE_URL")
        self.admin = None
        if url:
            self.schema = "test_" + uuid.uuid4().hex
            self.admin = create_engine(url)
            with self.admin.begin() as conn:
                conn.execute(text("CREATE SCHEMA " + self.schema))
            self.engine = create_engine(
                url, connect_args={"options": "-c search_path=" + self.schema}
            )
            metadata.create_all(self.engine)
        else:
            self.engine = connect("sqlite:///:memory:")

    def tearDown(self):
        self.engine.dispose()
        if self.admin is not None:
            with self.admin.begin() as conn:
                conn.execute(text("DROP SCHEMA " + self.schema + " CASCADE"))
            self.admin.dispose()

    def test_transaction_rolls_back_with_checkpoint(self):
        with self.assertRaises(RuntimeError):
            process_page(self.engine, [event()], "test", 0, fail_before_checkpoint=True)
        self.assertEqual(checkpoint(self.engine, "test"), 0)
        with self.engine.connect() as c:
            self.assertEqual(
                c.execute(select(func.count()).select_from(raw_events)).scalar(), 0
            )
        process_page(self.engine, [event()], "test", 0)
        self.assertEqual(checkpoint(self.engine, "test"), 1)

    def test_replay_and_late_correction(self):
        process_page(
            self.engine,
            [
                event(),
                event(),
                event(event_id="e2", revision=2, quantity=5),
                event(event_id="e3"),
            ],
            "test",
            0,
        )
        with self.engine.connect() as c:
            rows = c.execute(select(order_lines)).mappings().all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity"], 5)

    def test_bad_schema_is_quarantined(self):
        result = process_page(self.engine, [event(schema_version=2)], "test", 0)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(checkpoint(self.engine, "test"), 1)

    def test_same_id_different_content_fails_atomically(self):
        with self.assertRaises(ValueError):
            process_page(self.engine, [event(), event(quantity=9)], "test", 0)
        self.assertEqual(checkpoint(self.engine, "test"), 0)

    def test_same_revision_different_content_rejected(self):
        with self.assertRaises(ValueError):
            process_page(
                self.engine, [event(), event(event_id="e2", quantity=9)], "test", 0
            )

    def test_cancellation_and_zero_day_export(self):
        rows = [
            event(),
            event(event_id="e2", revision=2, status="cancelled"),
            event(event_id="e3", line_id="l2", order_date="2025-01-03"),
        ]
        process_page(self.engine, rows, "test", 0)
        with tempfile.TemporaryDirectory() as d:
            export(self.engine, d)
            self.assertIn("2025-01-03", Path(d, "daily_demand.csv").read_text())
            self.assertIn("s1,2025-01-01,0,0", Path(d, "daily_demand.csv").read_text())
            self.assertIn("s1,2025-01-02,0,0", Path(d, "daily_demand.csv").read_text())

    def test_resume_file_from_last_committed_page(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "events.jsonl")
            path.write_text(
                "\n".join(
                    json.dumps(event(event_id=f"e{i}", line_id=f"l{i}"))
                    for i in range(5)
                )
            )
            with self.assertRaises(RuntimeError):
                ingest_file(self.engine, path, page_size=2, fail_page=1)
            self.assertEqual(checkpoint(self.engine, str(path.resolve())), 2)
            self.assertEqual(ingest_file(self.engine, path, page_size=2), 5)
            with self.engine.connect() as c:
                self.assertEqual(
                    c.execute(select(func.count()).select_from(order_lines)).scalar(), 5
                )

    def test_blank_lines_append_and_resume_preserve_record_offsets(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "events.jsonl")
            path.write_text("\n" + json.dumps(event()) + "\n \n", encoding="utf-8")
            self.assertEqual(ingest_file(self.engine, path, page_size=2), 1)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event(event_id="e2", line_id="l2")) + "\n")
            self.assertEqual(ingest_file(self.engine, path, page_size=2), 2)
            self.assertEqual(ingest_file(self.engine, path, page_size=2), 2)
            with self.engine.connect() as c:
                self.assertEqual(c.execute(select(func.count()).select_from(order_lines)).scalar(), 2)

    def test_malformed_json_keeps_earlier_pages_but_not_current_page(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "events.jsonl")
            prefix = "\n".join(json.dumps(event(event_id=f"e{i}", line_id=f"l{i}")) for i in range(3))
            path.write_text(prefix + "\n{invalid\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid JSON at line 4"):
                ingest_file(self.engine, path, page_size=2)
            self.assertEqual(checkpoint(self.engine, str(path.resolve())), 2)
            with self.engine.connect() as c:
                self.assertEqual(c.execute(select(func.count()).select_from(raw_events)).scalar(), 2)
            # Repair only the uncommitted suffix, leaving the committed prefix intact.
            path.write_text(prefix + "\n" + json.dumps(event(event_id="e3", line_id="l3")), encoding="utf-8")
            self.assertEqual(ingest_file(self.engine, path, page_size=2), 4)

    def test_truncated_file_does_not_reset_committed_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "events.jsonl")
            path.write_text(json.dumps(event()), encoding="utf-8")
            ingest_file(self.engine, path)
            path.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "truncated"):
                ingest_file(self.engine, path)
            self.assertEqual(checkpoint(self.engine, str(path.resolve())), 1)


if __name__ == "__main__":
    unittest.main()
