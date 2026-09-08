import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("scan", Path(__file__).resolve().parents[1] / "scripts/scan.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
NOW = datetime(2026, 9, 9, 2, 17, tzinfo=timezone.utc)


def series():
    end = datetime(2026, 9, 8)
    dates = sorted((end - timedelta(days=i)).date().isoformat() for i in range(64))
    return {date: 100+i for i, date in enumerate(dates)}


class ScanTests(unittest.TestCase):
    def test_completed_bars_exclude_intraday(self):
        noon = datetime(2026, 9, 8, 16, tzinfo=timezone.utc)
        self.assertEqual(str(scan.completed_through(noon)), "2026-09-07")
        self.assertEqual(str(scan.completed_through(NOW)), "2026-09-08")

    def test_bars_filtered_and_sorted(self):
        raw = [{"t":"2026-09-09T04:00:00Z", "c":30}, {"t":"2026-09-08T04:00:00Z", "c":20}, {"t":"2026-09-07T04:00:00Z", "c":float('nan')}]
        self.assertEqual(scan.normalize(raw, scan.completed_through(NOW)), {"2026-09-08":20})

    def test_unaligned_data_not_a_signal(self):
        benchmark = series()
        stock = dict(benchmark)
        stock.pop(max(stock))
        row = scan.stock_row({"symbol":"AAA"}, stock, benchmark, NOW)
        self.assertEqual(row["status"], "Unavailable")
        self.assertIsNone(row["excess_63d"])

    def test_missing_session_not_compressed(self):
        benchmark = series()
        stock = dict(benchmark)
        del stock[sorted(stock)[10]]
        self.assertEqual(scan.stock_row({"symbol":"AAA"}, stock, benchmark, NOW)["status"], "Unavailable")

    def test_excess_is_percentage_points(self):
        benchmark = series()
        stock = {d:100+2*i for i,d in enumerate(benchmark)}
        row = scan.stock_row({"symbol":"AAA"}, stock, benchmark, NOW)
        self.assertAlmostEqual(row["excess_63d"], 63)
        self.assertEqual(row["status"], "Research")

    def test_stale_data_never_screened(self):
        values = series()
        row = scan.stock_row({"symbol":"AAA"}, values, values, NOW+timedelta(days=6))
        self.assertEqual(row["status"], "Unavailable")

    def test_feed_cashtags_and_dates(self):
        raw = b'<rss><channel><item><title>Review $AAA and BBB</title><link>https://example.com/article?utm_source=test</link><pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        source = {"name":"Test", "url":"https://example.com/feed"}
        entries = scan.parse_feed(raw, source, ["AAA", "BBB"], NOW)
        self.assertEqual(entries[0]["symbols"], ["AAA"])
        self.assertEqual(entries[0]["url"], "https://example.com/article")
        self.assertEqual(entries[0]["first_seen_at"], scan.stamp(NOW))
        self.assertEqual(scan.parse_feed(raw, source, ["AAA"], NOW+timedelta(days=9)), [])

    def test_atom_and_undated_items(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>$AAA</title><link href="https://example.com/a"/><published>2026-09-08T16:00:00Z</published></entry><entry><title>$AAA</title><link href="https://example.com/b"/></entry></feed>'
        self.assertEqual(len(scan.parse_feed(raw, {"name":"Test","url":"https://example.com/feed"},["AAA"],NOW)),1)

    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError):
            scan.parse_feed(b'<!DOCTYPE rss><rss/>', {}, [], NOW)

    def test_pagination_keeps_later_symbols(self):
        pages = [json.dumps({"bars":{"AAA":[{"c":1}]},"next_page_token":"next"}).encode(), json.dumps({"bars":{"SPY":[{"c":2}]},"next_page_token":None}).encode()]
        with patch.dict(os.environ, {"ALPACA_API_KEY":"test", "ALPACA_SECRET_KEY":"test"}), patch.object(scan, "fetch", side_effect=pages):
            self.assertEqual(set(scan.get_bars(["AAA"], NOW)), {"AAA", "SPY"})

    def test_consensus_math_uses_latest_valid_period(self):
        rows = [
            {"symbol":"AAA","period":"2026-07-01","strongBuy":2,"buy":6,"hold":3,"sell":1,"strongSell":0},
            {"symbol":"AAA","period":"2026-08-01","strongBuy":3,"buy":9,"hold":5,"sell":2,"strongSell":1},
        ]
        result = scan.normalize_recommendation("AAA", rows, NOW)
        self.assertEqual(result["total"], 20)
        self.assertEqual(result["buy_pct"], 60)
        self.assertEqual(result["hold_pct"], 25)
        self.assertEqual(result["sell_pct"], 15)
        self.assertEqual(result["balance"], 0.45)
        self.assertEqual(result["status"], "Current")

    def test_consensus_zero_or_invalid_is_unavailable(self):
        zero = [{"symbol":"AAA","period":"2026-08-01","strongBuy":0,"buy":0,"hold":0,"sell":0,"strongSell":0}]
        self.assertEqual(scan.normalize_recommendation("AAA", zero, NOW)["status"], "Unavailable")
        self.assertEqual(scan.normalize_recommendation("AAA", {"bad":"shape"}, NOW)["status"], "Unavailable")

    def test_no_keys_produces_honest_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp)
            (root / "config").mkdir()
            (root / "config/watchlist.json").write_text('[{"symbol":"AAA","name":"Test"}]')
            (root / "config/sources.json").write_text('[]')
            payload = scan.run(NOW, root)
            self.assertEqual(payload["status"], "setup")
            self.assertIsNone(payload["stocks"][0]["close"])
            self.assertEqual(payload["consensus_status"], "setup")
            self.assertEqual(payload["analyst_consensus"], [])
            self.assertEqual(len(list((root / "data/scans").glob('*.json'))), 1)

    def test_failed_provider_never_keeps_success_status(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ALPACA_API_KEY":"test","ALPACA_SECRET_KEY":"test"}), patch.object(scan,"get_bars",side_effect=ValueError("failure")):
            root = Path(temp)
            (root / "config").mkdir()
            (root / "config/watchlist.json").write_text('[{"symbol":"AAA","name":"Test"}]')
            (root / "config/sources.json").write_text('[]')
            self.assertEqual(scan.run(NOW, root)["market_status"], "error")


if __name__ == "__main__":
    unittest.main()
