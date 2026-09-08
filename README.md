# Market Scout — setup guide

A personal stock-research dashboard for Collin. Version 0.1 sets up the collection and review foundation. It has no proven trading edge, predicted returns, AI confidence scores, brokerage orders, or real-money trading.

## What is ready

- Dark, responsive dashboard with stock search, screen filters, and evidence details.
- Read-only Alpaca IEX daily-data collector; all result pages are fetched.
- Transparent price-trend screen with matching SPY dates and stale-data checks.
- RSS/Atom collector for explicit watchlist cashtags, source links, publication time, and first-seen time.
- Optional analyst-consensus adapter with dated Buy/Hold/Sell distributions and honest missing-data states.
- Permanent per-run JSON archives committed by GitHub Actions, including failed scans.
- Browser-local paper-decision journal with backup export/import. It is a journal, not a portfolio simulator.
- Scheduled GitHub Actions workflow and optional GitHub Pages deployment.
- No third-party Python packages, npm packages, database service, or paid AI subscription required for this starter.

## 1. Create the GitHub repository

Go to https://github.com/new while signed in to your account (`samuelcollin410-afk`). Name the repository `market-scout`. Use a separate repository from your games and school sites. Add a README so that the main branch exists.

GitHub Free supports Pages for public repositories. Private-repository Pages requires an eligible paid plan, and a private repository does not automatically make the published website private. For a personal research site, use public only if you are comfortable making its code and published research visible. If you need a private dashboard, keep the repo private and use authenticated hosting instead of Pages.

Send the repository link back in chat to continue setup together. The starter has been prepared, but has not been uploaded to GitHub or deployed.

### Upload yourself (optional)

Extract `market-scout-starter.zip`. Upload the contents of the extracted `market-scout` folder to the root of your repository using Add file → Upload files. Replace the placeholder README with this one. Upload `config`, `dist`, `scripts`, `tests`, `.env.example`, `.gitignore`, and the `.github` folder. Do not upload only the ZIP: GitHub does not extract it for you.

Check that `.github/workflows/scan-and-publish.yml` appears under that exact path in GitHub. If your file picker hides `.github`, use Add file → Create new file, enter `.github/workflows/scan-and-publish.yml`, and paste the contents from the provided file. Commit to `main`.

## 2. Create an Alpaca paper account

Open https://app.alpaca.markets/signup and complete Alpaca's account flow. Use the paper-trading area and generate paper API credentials. Do not fund a live brokerage account for this step. This project calls only the market-data API, never order endpoints.

In your GitHub repository, open Settings → Secrets and variables → Actions → New repository secret. Add:

| GitHub secret name | Value |
| --- | --- |
| `ALPACA_API_KEY` | Your Alpaca paper API key ID |
| `ALPACA_SECRET_KEY` | Your Alpaca paper secret key |

Never paste actual secrets into chat, `.env.example`, source files, GitHub issues, website inputs, or screenshots. No secrets are needed in browser code. The supplied `.env.example` lists names only; the scanner does not automatically load .env files.

The separate analyst-consensus page supports an optional `FINNHUB_API_KEY` repository secret. Before adding it, confirm that your Finnhub tier includes the recommendation endpoint and permits your intended public display. If the secret is absent, the page stays in an honest setup state. Market Scout combines Strong Buy with Buy and Strong Sell with Sell, keeps Hold separate, labels periods older than 120 days stale, and never converts missing coverage into Hold. This vendor aggregate is not firm-deduplicated and must not be added to another vendor aggregate as if it created new independent opinions.

Alpaca's paper-only data is IEX, one exchange. It is not a complete consolidated market feed. Use the free available access initially; paid data is not necessary just to test this starter. Check your data provider's display/redistribution terms before making fetched market data publicly available.

## 3. Run a scan

Open Actions → Scan and publish → Run workflow on `main`. Allow Actions if GitHub asks you to enable it. The first push can run without credentials; it will show an honest setup state, not fabricated data.

Open the run summary. `Market status: ok` means the market-data collector succeeded; it does not establish investment performance. If it says `setup`, add both repository secrets. If it says `error`, verify the paper credentials and data permissions. Invalid feeds have their own error status in the Source feed view.

The workflow commits the new snapshot and archives to `main`. If a repository or organization policy blocks bot writes or requires pull requests, the preservation step stops. Use the approved repository workflow rather than bypassing branch protections. On a new personal repository, check Settings → Actions → General → Workflow permissions if GitHub reports a write-permission error.

## 4. Publish the dashboard when ready

Settings → Pages → Build and deployment → Source: **GitHub Actions**.

Settings → Secrets and variables → Actions → Variables → New repository variable:

| Variable | Value |
| --- | --- |
| `ENABLE_PAGES` | `true` |

Run Scan and publish again. The deployment job returns your actual site link when it succeeds. Deployment stays off until this variable is set. Only `dist` is uploaded as the website; scripts and secrets are not bundled in it. A public repository still exposes all tracked files and archives.

The Refresh data button reloads the most recently published snapshot. It cannot start a scan or access GitHub Secrets. To collect new data, run the workflow or wait for the schedule.

## 5. Pick stocks and trader sources

`config/watchlist.json` contains 12 initial large-company examples across several sectors. These are implementation examples, not stock recommendations or a statistically selected universe. Change the list to your chosen symbols; the collector accepts 1–200 unique symbols.

`config/sources.json` starts empty. Send the names or URLs of 3–5 traders you want to evaluate. We can check which provide authorized RSS/Atom feeds or APIs before adding them.

For an RSS/Atom source, the format is:

```json
[
  {"name": "Name of a source you selected", "url": "https://example.com/feed.xml"}
]
```

Replace the example with a real authorized feed. HTML profile pages, YouTube pages, X profiles, and login-only newsletters are not RSS URLs. Never put private feed URLs with subscription tokens into a public repository. The collector supports up to 20 feeds, detects explicit uppercase cashtags such as `$AAPL`, skips missing/future publication dates, and collects only the last 7 days. A cashtag is a mention, not evidence that the author recommended a trade. It does not yet infer sentiment, buy/sell intent, or trader credibility.

Only headlines, symbols, dates, and original links are retained; article bodies are used for matching but not published. Exact normalized article URLs are deduplicated across feeds. Syndicated stories with different URLs may still be duplicates. First-seen time records when this tool collected an article, not when the public first saw it.

## The screen, explained

A stock is labeled **Research** only if all three conditions hold:

1. Its latest adjusted close is above the mean of its last 50 matching daily closes.
2. Its 20-session adjusted return is positive.
3. Its 63-session adjusted return exceeds SPY's over the exact same dates.

**Watch** means it fails at least one condition; it is not a sell instruction. **Unavailable** means the data cannot support the screen. No ranks or win probabilities are invented.

The scanner requires 64 matching observations for the 63-session return. It excludes incomplete daily bars, refuses mismatched end dates, and rejects data older than four calendar days. Daily bars use Alpaca's `all` corporate-action adjustment: the displayed adjusted close is not an executable quote. SPY is an ETF proxy for the S&P 500, not the index itself. `pp` means percentage points. These are historical price comparisons, not portfolio performance or a validated backtest.

## Schedule and storage

The schedule is **02:17 UTC Tuesday–Saturday**, equivalent to **10:17 pm Eastern daylight time / 9:17 pm Eastern standard time on Monday–Friday evenings**. Scans are scheduled after U.S. extended trading. Holidays can produce the same most recent bar. Manual runs before 9 pm Eastern deliberately exclude that day's bar.

GitHub can delay scheduled jobs; this is not a real-time trading service. Scheduled workflows run on the default branch and can be disabled in inactive public repositories. If scans stop, check Actions and the last-scan date. Never label old data live.

- `dist/data/latest.json`: the latest dashboard snapshot.
- `data/scans/`: historical scans committed by the workflow; first observations are not retroactively replaced.
- `data/seen.json`: first-seen times for deduplication.
- Paper journal: this browser's local storage only. Export backups regularly, especially before clearing browser data or changing site addresses.

The journal records your supplied observed price and your decision time. It does not verify prices, fill trades, maintain cash, calculate profit, or synchronize devices. Private journal entries are not uploaded by the scanner.

## Local preview and checks

With Python 3.12 installed, open a terminal in the project folder:

```bash
python -m http.server 8000 --directory dist
```

Then open http://localhost:8000. On Windows, use `py` instead of `python` if that is how Python is installed. Do not simply double-click index.html; fetching the JSON snapshot requires a local web server.

Run the scanner from a terminal with the two credential variables already set securely, or omit them to test the setup state:

```bash
python scripts/scan.py
python -m unittest discover -s tests -v
python scripts/check_site.py
node --check dist/app.js
```

GitHub Actions supplies Python and Node on its runner; you do not need to install these locally to use the hosted workflow. Test fixtures use synthetic values and never appear in the dashboard. Local scans create ignored `data/` files; the workflow deliberately commits them for durability.

## Next development stages

After the first analyst-provider test, move from vendor totals to structured firm-level recommendations with original dates, rating changes, withdrawals, and source-grounded evidence. Only then consider combining providers, because copied ratings must count once. A later portfolio simulator should use next-available execution prices, costs, corporate actions, and matching benchmark cash flows. Compare the simple rule against versions that add source signals, and track all suggestions prospectively, including losses. AI analysis, Form 4/13F ingestion, trader rankings, push notifications, and automatic buy/sell suggestions are not yet implemented.

No trading performance was measured in this setup. The starter must not be presented as a proven way to beat the S&P 500.

## Official documentation

- [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub scheduled workflows](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [Alpaca paper trading](https://docs.alpaca.markets/us/docs/paper-trading)
- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars)

GitHub Pages is intended here for a personal research site. Reassess hosting and applicable requirements before turning it into a commercial recommendation service or adding sensitive transactions.
