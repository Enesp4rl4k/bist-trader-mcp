# Changelog

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
