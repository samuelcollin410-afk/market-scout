"""Weekly paper-only portfolio experiment. This module has no live-trading URL."""
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
PAPER_BASE = "https://paper-api.alpaca.markets"
BOT_PREFIX = "market-scout-"


def stamp(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def api_request(path, method="GET", body=None):
    if not path.startswith("/v2/"):
        raise ValueError("Unsupported paper API path")
    headers = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
               "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
               "User-Agent": "MarketScout-paper/0.1", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(PAPER_BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Paper API response exceeds 1 MB")
        return json.loads(raw) if raw else None


def rank_candidates(snapshot, limit=5):
    consensus = {row.get("symbol"): row for row in snapshot.get("analyst_consensus", []) if isinstance(row, dict)}
    ranked = []
    for stock in snapshot.get("stocks", []):
        opinion = consensus.get(stock.get("symbol"), {})
        values = (stock.get("return_20d"), stock.get("excess_63d"), opinion.get("balance"))
        if stock.get("status") != "Research" or opinion.get("status") != "Current":
            continue
        if opinion.get("total", 0) < 10 or opinion.get("buy_pct", 0) < 60 or opinion.get("sell_pct", 100) > 20:
            continue
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            continue
        score = stock["excess_63d"] + 0.25 * stock["return_20d"] + 10 * opinion["balance"]
        ranked.append({"symbol": stock["symbol"], "name": stock.get("name", stock["symbol"]),
                       "score": round(score, 4), "return_20d": stock["return_20d"],
                       "excess_63d": stock["excess_63d"], "buy_pct": opinion["buy_pct"],
                       "opinion_count": opinion["total"], "opinion_period": opinion["period"]})
    return sorted(ranked, key=lambda row: (-row["score"], row["symbol"]))[:limit]


def update_snapshot(root, snapshot):
    atomic_json(root / "dist/data/latest.json", snapshot)
    generated = snapshot.get("generated_at")
    for path in sorted((root / "data/scans").glob("*.json"), reverse=True)[:3]:
        try:
            archived = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if archived.get("generated_at") == generated:
            archived["paper_bot"] = snapshot["paper_bot"]
            atomic_json(path, archived)
            break


def state_default():
    return {"schema_version": 1, "managed_symbols": [], "last_rebalance_at": None,
            "last_result": None, "last_actions": []}


def run(now=None, root=ROOT, api=api_request):
    now = now or datetime.now(timezone.utc)
    snapshot = json.loads((root / "dist/data/latest.json").read_text())
    state_path = root / "data/paper_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else state_default()
    targets = rank_candidates(snapshot)
    target_symbols = [row["symbol"] for row in targets]
    enabled = os.environ.get("ENABLE_AUTO_PAPER_TRADING", "").lower() == "true"
    try:
        budget = float(os.environ.get("PAPER_BUDGET_USD") or 10_000)
    except ValueError:
        budget = 10_000
    budget = min(max(budget, 500), 100_000)
    summary = {"mode": "ALPACA PAPER ONLY", "enabled": enabled, "status": "preview",
               "message": "Automatic paper orders are disabled. These are the current rule-based targets.",
               "strategy": "Weekly top five: trend screen + current analyst aggregate; 18% of the fixed paper budget per holding.",
               "budget_usd": budget, "target_symbols": target_symbols, "candidates": targets,
               "last_rebalance_at": state.get("last_rebalance_at"),
               "actions": state.get("last_actions", []) if isinstance(state.get("last_actions", []), list) else []}
    snapshot["paper_bot"] = summary
    generated = snapshot.get("generated_at")
    try:
        generated_at = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        generated_at = None
    if not generated_at:
        summary.update(status="blocked", message="The research snapshot has no valid timestamp. No orders submitted.")
    elif now - generated_at > timedelta(hours=6) or now < generated_at:
        summary.update(status="blocked", message="The research snapshot is stale or future-dated. No orders submitted.")
    elif snapshot.get("market_status") != "ok" or snapshot.get("consensus_status") != "ok":
        summary.update(status="blocked", message="Current price and analyst data are both required. No orders submitted.")
    elif enabled:
        last = state.get("last_rebalance_at")
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            last_dt = None
        if last_dt and now - last_dt < timedelta(days=7):
            summary.update(status="waiting", message="The weekly paper rebalance is not due yet. No orders submitted.")
        elif not os.environ.get("ALPACA_API_KEY") or not os.environ.get("ALPACA_SECRET_KEY"):
            summary.update(status="blocked", message="Paper credentials are unavailable. No orders submitted.")
        else:
            actions = []
            managed = set(state.get("managed_symbols", []))
            action_path = root / "data/paper_actions" / (now.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json")
            try:
                if api("/v2/clock").get("is_open"):
                    raise RuntimeError("Market is open")
                account = api("/v2/account")
                if account.get("status") != "ACTIVE" or account.get("trading_blocked"):
                    raise RuntimeError("Paper account unavailable")
                equity = float(account.get("equity", 0))
                if not math.isfinite(equity) or equity <= 0:
                    raise RuntimeError("Paper equity unavailable")
                budget = round(min(budget, equity * 0.9), 2)
                summary["budget_usd"] = budget
                if api("/v2/orders?" + urllib.parse.urlencode({"status": "open", "limit": 500})):
                    raise RuntimeError("Open paper orders exist")
                positions = api("/v2/positions")
                positions_by_symbol = {p["symbol"]: p for p in positions if p.get("asset_class") == "us_equity"}
                run_id = now.strftime("%Y%m%d%H%M%S")
                for symbol in sorted(managed - set(target_symbols)):
                    position = positions_by_symbol.get(symbol)
                    if not position:
                        managed.discard(symbol)
                        continue
                    qty = float(position.get("qty", 0))
                    if qty <= 0:
                        continue
                    order = {"symbol": symbol, "qty": str(qty), "side": "sell", "type": "market",
                             "time_in_force": "day", "client_order_id": f"{BOT_PREFIX}{run_id}-{symbol}-sell"}
                    api("/v2/orders", "POST", order)
                    actions.append({"symbol": symbol, "side": "sell", "quantity": qty, "status": "submitted"})
                target_value = round(budget * 0.18, 2)
                for symbol in target_symbols:
                    position = positions_by_symbol.get(symbol)
                    if position and symbol not in managed:
                        actions.append({"symbol": symbol, "side": "skip", "status": "outside-position-conflict"})
                        continue
                    current_value = float(position.get("market_value", 0)) if position else 0
                    notional = round(max(0, target_value - current_value), 2)
                    if notional < 50:
                        continue
                    asset = api("/v2/assets/" + urllib.parse.quote(symbol, safe=""))
                    if not asset.get("tradable") or not asset.get("fractionable"):
                        actions.append({"symbol": symbol, "side": "skip", "status": "not-fractionable-or-tradable"})
                        continue
                    order = {"symbol": symbol, "notional": str(notional), "side": "buy", "type": "market",
                             "time_in_force": "day", "client_order_id": f"{BOT_PREFIX}{run_id}-{symbol}-buy"}
                    api("/v2/orders", "POST", order)
                    managed.add(symbol)
                    actions.append({"symbol": symbol, "side": "buy", "notional_usd": notional, "status": "submitted"})
                    # Persist ownership after each accepted buy so a later failure cannot orphan it.
                    state["managed_symbols"] = sorted(managed)
                    atomic_json(state_path, state)
                submitted = any(action["side"] in ("buy", "sell") for action in actions)
                result_status = "submitted" if submitted else "no-change"
                state.update(managed_symbols=sorted(managed), last_rebalance_at=stamp(now),
                             last_result=result_status, last_actions=actions)
                atomic_json(state_path, state)
                summary.update(status=result_status,
                               message="Weekly paper orders were submitted for the next regular session." if submitted else
                                       "The weekly check found no paper-position changes to submit.",
                               last_rebalance_at=state["last_rebalance_at"], actions=actions)
                atomic_json(action_path, {"schema_version": 1, "recorded_at": stamp(now),
                                          "result": summary["status"], "target_symbols": target_symbols, "actions": actions})
            except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, urllib.error.URLError):
                if actions:
                    state.update(managed_symbols=sorted(managed), last_rebalance_at=stamp(now),
                                 last_result="partial", last_actions=actions)
                    atomic_json(state_path, state)
                    atomic_json(action_path, {"schema_version": 1, "recorded_at": stamp(now), "result": "partial",
                                              "target_symbols": target_symbols, "actions": actions})
                summary.update(status="partial" if actions else "blocked",
                               message="The paper batch stopped after some orders were submitted; no automatic retry will occur." if actions else
                                       "The paper rebalance was safely blocked. Check account status, open orders, and assets. No retry was attempted.",
                               last_rebalance_at=state.get("last_rebalance_at"), actions=actions)
    update_snapshot(root, snapshot)
    print("Paper bot status: " + summary["status"] + "; targets: " + str(len(target_symbols)) + "; actions: " + str(len(summary["actions"])))
    return summary


if __name__ == "__main__":
    run()
