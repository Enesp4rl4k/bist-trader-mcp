# Changelog

## [0.5.0] — 2026-10-21

### Added

- **Simple views** — `forecast_next_candles` (30 possible futures, HTML chart) and `get_simple_price_action` (trend, levels, AL/SAT/BEKLE, one plan)
- **Measurement** — walk-forward `backtest_price_action` / `backtest_price_action_universe` (no look-ahead, R after costs, factor attribution) and `evaluate_forecast_accuracy`
- **Learned weights** — confluence factors re-weighted from backtests, validated out of sample; setup track records veto losing setup types
- **Risk engine** — sizing, open-risk cap, loss circuit breakers, correlation clusters, liquidity, tavan/taban, macro and earnings-window warnings (`check_trade_risk`, `get_portfolio_risk`, `set_risk_config`)
- **Daily pipeline** — scan → risk check → journal → replay outcomes → HTML report (`run_daily_pipeline`, `bist-trader-daily`)
- **Live dashboard** — in-chat MCP Apps panel (Claude, Cursor, VS Code) + browser mode for Codex/terminals (`open_dashboard`, `bist-trader-dashboard`)
- **Alerts** — Telegram + local outbox (`check_alerts`, `bist-trader-alerts`)
- **Paper account** — TL equity, drawdown, live-vs-backtest check (`get_paper_account`)
- **Company events** — SPK filing windows + KAP corporate actions (`get_company_events`)
- **Company valuation** — driver FCFF DCF, sensitivity, scenarios, Monte Carlo, DDM, bank residual-income model, peer multiples, beta estimation (`value_company`, `estimate_equity_beta`)
- **Background jobs** (`start_job` / `get_job`), **tool profiles** (`BIST_TOOL_PROFILE`), `get_network_stats`

### Changed

- TradingView is the primary bar source; Yahoo/Binance are fallbacks (split-adjusted Yahoo for BIST)
- Sync tools run off the event loop; per-tool timeouts; uniform `{error, detail, tool}` errors
- Compact JSON output and trimmed floats (smaller tool results)
- TradingView path is found automatically (`TRADINGVIEW_MCP_PATH` still wins)
- Single version source (`bist_trader_mcp.__version__`)

### Fixed

- Plans with the target on the wrong side of the entry were offered with a positive R:R
- Concurrent journal writes could lose rows; a corrupt journal was silently overwritten
- `mcp` 2.x broke fresh installs (now pinned `<2`); 403s were retried 4 times
- Python 3.10 incompatibility in the LRU cache

## [0.4.0] — 2026-06-03

### Added

- **Fundamental–technical fusion** (`fundamental_technical_fusion`, `fundamental_score`) — single `trade_allowed` gate for `run_market_assistant`
- **`chat_report` v2** — Fusion section, `technical_approved` vs final execution
- **Enriched fundamentals** — sector rotation (mapped tickers), VIOP term structure, macro overlay (EVDS), news headlines from KAP
- **BIST holiday filter** in session bar cleanup
- **EOD HTF fallback** when TradingView HTF quality is thin
- **FVG zone labels** on TradingView (top/bot + ZONE marker)
- MCP prompt **`trade-assistant`**
- Cursor rule **`.cursor/rules/trade-assistant.mdc`**
- GitHub Actions **pytest** workflow
- Unit tests for fusion and BIST calendar

### Changed

- `run_market_assistant` applies fusion after technical approval; blocks chart position when fusion disagrees
- Version aligned to **0.4.0** (open beta)

### Documentation

- [docs/ANALYSIS_PIPELINE.md](docs/ANALYSIS_PIPELINE.md) — gates, fusion, determinism
- [docs/PERFORMANCE_AND_CONSISTENCY.md](docs/PERFORMANCE_AND_CONSISTENCY.md) — latency, single-pass TA
- [docs/TRADE_ASSISTANT.md](docs/TRADE_ASSISTANT.md), [docs/README.md](docs/README.md) — index
- `chat_report.sections` + `trade_allowed` for LLM consumers
- README: trade assistant vs quant layers, 304 tests

## [0.3.0] — prior

- Market assistant, KAP enrich, TÜRİB, Elliott MTF, PA range/FVG, TradingView bridge
