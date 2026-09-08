import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("paper_trade", Path(__file__).resolve().parents[1] / "scripts/paper_trade.py")
paper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper)
NOW = datetime(2026, 9, 9, 2, 17, tzinfo=timezone.utc)


def snapshot():
    stocks, opinions = [], []
    for index, symbol in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")):
        stocks.append({"symbol": symbol, "name": symbol, "status": "Research",
                       "return_20d": 4 + index, "excess_63d": 3 + index})
        opinions.append({"symbol": symbol, "status": "Current", "total": 20,
                         "buy_pct": 70, "sell_pct": 10, "balance": .6, "period": "2026-09-01"})
    return {"generated_at": paper.stamp(NOW), "market_status": "ok", "consensus_status": "ok",
            "stocks": stocks, "analyst_consensus": opinions}


class PaperTradeTests(unittest.TestCase):
    def write_root(self, root):
        (root / "dist/data").mkdir(parents=True)
        (root / "data/scans").mkdir(parents=True)
        data = snapshot()
        (root / "dist/data/latest.json").write_text(json.dumps(data))
        (root / "data/scans/test.json").write_text(json.dumps(data))

    def test_ranking_is_limited_and_deterministic(self):
        result = paper.rank_candidates(snapshot())
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["symbol"], "FFF")
        self.assertNotIn("AAA", [row["symbol"] for row in result])

    def test_missing_or_stale_opinion_is_not_a_candidate(self):
        data = snapshot()
        data["analyst_consensus"][0]["status"] = "Stale"
        data["analyst_consensus"][1]["total"] = 0
        symbols = [row["symbol"] for row in paper.rank_candidates(data, limit=10)]
        self.assertNotIn("AAA", symbols)
        self.assertNotIn("BBB", symbols)

    def test_disabled_mode_never_calls_broker(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp)
            self.write_root(root)
            result = paper.run(NOW, root, api=lambda *args: self.fail("broker called"))
            self.assertEqual(result["status"], "preview")
            self.assertFalse(result["enabled"])
            saved = json.loads((root / "dist/data/latest.json").read_text())
            self.assertEqual(len(saved["paper_bot"]["target_symbols"]), 5)

    def test_enabled_mode_uses_paper_plan_and_preserves_outside_position(self):
        calls = []

        def fake_api(path, method="GET", body=None):
            calls.append((path, method, body))
            if path == "/v2/clock": return {"is_open": False}
            if path == "/v2/account": return {"status": "ACTIVE", "trading_blocked": False, "equity": "100000"}
            if path.startswith("/v2/orders?"): return []
            if path == "/v2/positions": return [{"symbol":"OUTSIDE","asset_class":"us_equity","qty":"3","market_value":"300"}]
            if path.startswith("/v2/assets/"): return {"tradable": True, "fractionable": True}
            if path == "/v2/orders" and method == "POST": return {"status": "accepted"}
            raise AssertionError(path)

        env = {"ENABLE_AUTO_PAPER_TRADING":"true", "ALPACA_API_KEY":"test", "ALPACA_SECRET_KEY":"test"}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, env, clear=True):
            root = Path(temp)
            self.write_root(root)
            result = paper.run(NOW, root, api=fake_api)
            self.assertEqual(result["status"], "submitted")
            self.assertEqual(len([a for a in result["actions"] if a["side"] == "buy"]), 5)
            self.assertFalse(any(body and body.get("symbol") == "OUTSIDE" for _, _, body in calls))
            self.assertTrue(all(not path.startswith("http") for path, _, _ in calls))
            self.assertEqual(paper.PAPER_BASE, "https://paper-api.alpaca.markets")

    def test_partial_batch_is_recorded_and_not_retried_immediately(self):
        submitted = 0

        def fake_api(path, method="GET", body=None):
            nonlocal submitted
            if path == "/v2/clock": return {"is_open": False}
            if path == "/v2/account": return {"status": "ACTIVE", "trading_blocked": False, "equity": "100000"}
            if path.startswith("/v2/orders?"): return []
            if path == "/v2/positions": return []
            if path.startswith("/v2/assets/"): return {"tradable": True, "fractionable": True}
            if path == "/v2/orders" and method == "POST":
                submitted += 1
                if submitted == 2: raise RuntimeError("synthetic rejection")
                return {"status": "accepted"}
            raise AssertionError(path)

        env = {"ENABLE_AUTO_PAPER_TRADING":"true", "ALPACA_API_KEY":"test", "ALPACA_SECRET_KEY":"test"}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, env, clear=True):
            root = Path(temp)
            self.write_root(root)
            result = paper.run(NOW, root, api=fake_api)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(result["actions"]), 1)
            state = json.loads((root / "data/paper_state.json").read_text())
            self.assertEqual(state["last_rebalance_at"], paper.stamp(NOW))
            second = paper.run(NOW, root, api=lambda *args: self.fail("immediate retry"))
            self.assertEqual(second["status"], "waiting")


if __name__ == "__main__":
    unittest.main()
