"""Daily research snapshot. Read-only APIs; no brokerage orders or AI calls."""
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")


def stamp(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch(url, headers=None):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("HTTPS source required")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "MarketScout/0.1"})
            with urllib.request.urlopen(req, timeout=25) as response:
                content = response.read(5_000_001)
                if len(content) > 5_000_000:
                    raise ValueError("Response exceeds 5 MB")
                return content
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2 ** attempt)


def completed_through(now):
    local = now.astimezone(NY)
    # Wait beyond extended trading, never use today's partial daily candle.
    return local.date() if local.hour >= 21 else local.date() - timedelta(days=1)


def get_bars(symbols, now):
    headers = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
               "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}
    params = {"symbols": ",".join(sorted(set(symbols + ["SPY"]))), "timeframe": "1Day",
              "start": stamp(now - timedelta(days=400)), "end": stamp(now - timedelta(minutes=20)),
              "adjustment": "all", "feed": "iex", "sort": "asc", "limit": 10000}
    result = {}
    seen_tokens = set()
    for _ in range(100):
        payload = json.loads(fetch("https://data.alpaca.markets/v2/stocks/bars?" + urllib.parse.urlencode(params), headers))
        for symbol, bars in payload.get("bars", {}).items():
            result.setdefault(symbol, []).extend(bars)
        token = payload.get("next_page_token")
        if not token:
            return result
        if token in seen_tokens:
            raise ValueError("Repeated data pagination token")
        seen_tokens.add(token)
        params["page_token"] = token
    raise ValueError("Too many data pages")


def blank_consensus(symbol, message="No analyst data was returned."):
    return {"symbol": symbol, "source": "Finnhub analyst aggregate", "period": None,
            "strong_buy": None, "buy": None, "hold": None, "sell": None,
            "strong_sell": None, "total": None, "buy_pct": None, "hold_pct": None,
            "sell_pct": None, "balance": None, "status": "Unavailable", "message": message}


def normalize_recommendation(symbol, rows, now):
    """Normalize one provider aggregate without presenting it as a profit probability."""
    if not isinstance(rows, list):
        return blank_consensus(symbol, "The analyst provider returned an unexpected format.")
    valid = []
    for item in rows:
        if not isinstance(item, dict) or item.get("symbol", symbol) != symbol:
            continue
        period = item.get("period")
        try:
            period_date = datetime.strptime(period, "%Y-%m-%d").date()
            counts = {key: int(item[key]) for key in ("strongBuy", "buy", "hold", "sell", "strongSell")}
        except (KeyError, TypeError, ValueError):
            continue
        if any(value < 0 for value in counts.values()):
            continue
        valid.append((period_date, counts))
    if not valid:
        return blank_consensus(symbol)
    period_date, counts = max(valid, key=lambda row: row[0])
    bullish = counts["strongBuy"] + counts["buy"]
    bearish = counts["sell"] + counts["strongSell"]
    total = bullish + counts["hold"] + bearish
    if total == 0:
        return blank_consensus(symbol, "The latest analyst period has zero recorded opinions.")
    age = (now.astimezone(NY).date() - period_date).days
    stale = age > 120
    return {"symbol": symbol, "source": "Finnhub analyst aggregate", "period": period_date.isoformat(),
            "strong_buy": counts["strongBuy"], "buy": bullish, "hold": counts["hold"],
            "sell": bearish, "strong_sell": counts["strongSell"], "total": total,
            "buy_pct": round(bullish / total * 100, 2),
            "hold_pct": round(counts["hold"] / total * 100, 2),
            "sell_pct": round(bearish / total * 100, 2),
            "balance": round((bullish - bearish) / total, 4),
            "status": "Stale" if stale else "Current",
            "message": "Latest provider period is over 120 days old." if stale else
                       "Latest provider aggregate. Firm-level deduplication is not available in this feed."}


def get_analyst_consensus(symbols, now):
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        return "setup", "Add an authorized analyst-data key to collect consensus figures.", []
    rows = []
    failures = 0
    for symbol in symbols:
        params = urllib.parse.urlencode({"symbol": symbol, "token": token})
        try:
            raw = fetch("https://finnhub.io/api/v1/stock/recommendation?" + params)
            rows.append(normalize_recommendation(symbol, json.loads(raw), now))
        except Exception:
            failures += 1
            rows.append(blank_consensus(symbol, "The analyst-data request failed for this symbol."))
    usable = sum(row["status"] in ("Current", "Stale") for row in rows)
    if usable == 0:
        return "error", "No usable analyst consensus was returned. Check the key, access tier, and provider status.", rows
    if failures or usable < len(symbols):
        return "partial", "Analyst consensus loaded for some stocks; review unavailable and stale rows.", rows
    return "ok", "Analyst consensus loaded. Percentages describe published opinions, not the chance of profit.", rows


def normalize(bars, cutoff):
    output = {}
    for bar in bars:
        dt = datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).astimezone(NY).date()
        close = float(bar["c"])
        if dt <= cutoff and math.isfinite(close) and close > 0:
            output[dt.isoformat()] = close
    return dict(sorted(output.items()))


def stock_row(item, bars, benchmark, now):
    row = {**item, "status": "Unavailable", "reason": "Awaiting market data.", "close": None,
           "return_20d": None, "excess_63d": None, "as_of": None, "window_start": None}
    if not bars:
        return row
    dates = sorted(bars)
    last = dates[-1]
    row.update(close=bars[last], as_of=last)
    if (now.astimezone(NY).date() - datetime.fromisoformat(last).date()).days > 4:
        row["reason"] = "Price data is more than four calendar days old. No screen issued."
        return row
    # Never compare mismatched dates or compress away missing sessions.
    if not benchmark or last != max(benchmark):
        row["reason"] = "Stock and benchmark end dates do not match. No screen issued."
        return row
    window = sorted(benchmark)[-64:]
    if len(window) < 64 or any(day not in bars for day in window):
        row["reason"] = "Need 64 matching daily observations with SPY. No screen issued."
        return row
    start, start20 = window[0], window[-21]
    r20 = (bars[last] / bars[start20] - 1) * 100
    r63 = (bars[last] / bars[start] - 1) * 100
    b63 = (benchmark[last] / benchmark[start] - 1) * 100
    above = bars[last] > sum(bars[day] for day in window[-50:]) / 50
    candidate = above and r20 > 0 and r63 > b63
    row.update(status="Research" if candidate else "Watch", return_20d=round(r20, 4),
               excess_63d=round(r63-b63, 4), window_start=start,
               reason="Passes all three price-trend conditions. Unvalidated research candidate, not a buy recommendation."
               if candidate else "Does not pass all three price-trend conditions. This is not a sell recommendation.")
    return row


def date_text(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None
    return stamp(dt)


def parse_feed(raw, source, symbols, now):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Unsupported XML declaration")
    root = ET.fromstring(raw)
    entries = [e for e in root.iter() if e.tag.split("}")[-1] in ("item", "entry")]
    result = []
    for entry in entries[:500]:
        fields = {}
        for child in entry:
            key = child.tag.split("}")[-1]
            if key == "link":
                if child.get("rel", "alternate") == "alternate":
                    fields[key] = child.get("href") or child.text or ""
            else:
                fields[key] = "".join(child.itertext())
        title = re.sub(r"<[^>]*>", "", html.unescape(fields.get("title", "")))[:500]
        body = html.unescape(" ".join(fields.get(k, "") for k in ("description", "summary", "content", "encoded")))
        matched = sorted(set(re.findall(r"\$([A-Z][A-Z0-9.\-]{0,9})\b", title + " " + body)) & set(symbols))
        published = date_text(fields.get("pubDate") or fields.get("published") or fields.get("updated"))
        if not matched or not published:
            continue
        age = now - datetime.fromisoformat(published.replace("Z", "+00:00"))
        if age < timedelta(0) or age > timedelta(days=7):
            continue
        link = urllib.parse.urljoin(source["url"], fields.get("link", ""))
        if not fields.get("link") or urllib.parse.urlparse(link).scheme != "https":
            continue
        # Same article linked by several feeds is one mention, not independent evidence.
        clean = urllib.parse.urlsplit(link)
        query = urllib.parse.parse_qsl(clean.query)
        query = [(k, v) for k, v in query if not k.startswith("utm_") and k not in ("ref", "fbclid")]
        link = urllib.parse.urlunsplit((clean.scheme, clean.netloc.lower(), clean.path, urllib.parse.urlencode(query), ""))
        ident = hashlib.sha256(link.encode()).hexdigest()[:24]
        result.append({"id": ident, "source": source["name"], "title": title, "symbols": matched,
                       "url": link, "published_at": published, "first_seen_at": stamp(now)})
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def run(now=None, root=ROOT):
    now = now or datetime.now(timezone.utc)
    watchlist = json.loads((root / "config/watchlist.json").read_text())
    sources = json.loads((root / "config/sources.json").read_text())
    if not isinstance(watchlist, list) or not 1 <= len(watchlist) <= 200:
        raise ValueError("Configure 1 to 200 stocks")
    symbols = [item["symbol"] for item in watchlist]
    if len(set(symbols)) != len(symbols) or any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", s) for s in symbols):
        raise ValueError("Watchlist symbols must be unique uppercase tickers")
    if not isinstance(sources, list) or len(sources) > 20:
        raise ValueError("Configure at most 20 sources")
    payload = {"schema_version": 1, "generated_at": stamp(now), "status": "setup", "market_status": "setup",
               "message": "Market data is not connected. Add your two Alpaca repository secrets, then run the workflow.",
               "benchmark": {"symbol": "SPY", "return_63d": None}, "stocks": [], "mentions": [], "sources": [],
               "consensus_status": "setup", "consensus_message": "Analyst consensus is not connected.",
               "analyst_consensus": []}
    bars = {}
    benchmark = {}
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
        try:
            raw = get_bars(symbols, now)
            bars = {s: normalize(b, completed_through(now)) for s, b in raw.items()}
            benchmark = bars.get("SPY", {})
            payload.update(status="ok", market_status="ok", message="Daily research scan complete. Review the evidence before recording a paper decision.")
        except Exception:
            # Do not print provider response bodies, credential-bearing requests, or source URLs.
            payload.update(status="error", market_status="error", message="Market data request failed. Check the Alpaca paper keys and data access, then retry. No new screen was issued.")
    payload["stocks"] = [stock_row(item, bars.get(item["symbol"], {}), benchmark, now) for item in watchlist]
    consensus_status, consensus_message, consensus = get_analyst_consensus(symbols, now)
    payload.update(consensus_status=consensus_status, consensus_message=consensus_message,
                   analyst_consensus=consensus)
    if payload["market_status"] == "ok":
        if not benchmark or all(s["status"] == "Unavailable" for s in payload["stocks"]):
            payload.update(status="partial", market_status="partial", message="No usable aligned market window was returned. Review stock details and data access.")
        elif any(s["status"] == "Unavailable" for s in payload["stocks"]):
            payload.update(status="partial", message="Scan complete with some unavailable stocks. Check individual dates and missing-data notes.")
        dates = sorted(benchmark)
        if len(dates) >= 64 and (now.astimezone(NY).date()-datetime.fromisoformat(dates[-1]).date()).days <= 4:
            payload["benchmark"].update(return_63d=round((benchmark[dates[-1]]/benchmark[dates[-64]]-1)*100,4), as_of=dates[-1])
    seen_file = root / "data/seen.json"
    seen = json.loads(seen_file.read_text()) if seen_file.exists() else {}
    collected = {}
    for source in sources:
        info = {"name": source["name"], "status": "ok", "message": "Feed checked. Only explicit watchlist cashtags are matched."}
        try:
            for mention in parse_feed(fetch(source["url"]), source, symbols, now):
                if mention["id"] not in seen:
                    seen[mention["id"]] = mention["first_seen_at"]
                mention["first_seen_at"] = seen[mention["id"]]
                collected.setdefault(mention["id"], mention)
        except Exception:
            info.update(status="error", message="Feed could not be read. Check its URL, permission, and RSS/Atom format.")
            if payload["status"] == "ok":
                payload.update(status="partial", message="Market scan complete, but at least one source feed failed. See Source feed.")
        payload["sources"].append(info)
    payload["mentions"] = sorted(collected.values(), key=lambda m:m["published_at"], reverse=True)
    atomic_json(seen_file, seen)
    # Unique run files retain every scan including failures; first_seen is never backdated.
    archive = root / "data/scans" / (now.strftime("%Y-%m-%dT%H-%M-%S-%fZ") + ".json")
    atomic_json(archive, payload)
    atomic_json(root / "dist/data/latest.json", payload)
    print("Scan status: " + payload["status"] + "; stocks: " + str(len(watchlist)) + "; mentions: " + str(len(collected)))
    return payload


if __name__ == "__main__":
    run()
