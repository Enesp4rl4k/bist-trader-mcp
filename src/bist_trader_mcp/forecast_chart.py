"""Self-contained HTML chart for ``candle_forecast.forecast_candles``.

Dark candlestick chart (inline SVG, no JS/CDN) with the mean forecast line,
the lowest→highest run band and a side panel: Up/Down %, volatility
amplification, mean forecast, full range and a "how it works" box.
"""

from __future__ import annotations

import html
from typing import Any

_W, _H = 1100, 560
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 10, 70, 20, 30


def _fmt(x: float) -> str:
    return f"{x:,.2f}"


def render_forecast_html(
    forecast: dict[str, Any],
    closes: list[float],
    highs: list[float],
    lows: list[float],
    opens: list[float] | None = None,
    *,
    symbol: str = "",
    show_bars: int = 120,
    currency: str = "",
) -> str:
    """Return a full HTML document visualising the forecast next to history."""
    if opens is None:
        opens = [closes[0]] + closes[:-1]
    k = max(10, min(show_bars, len(closes)))
    o, h, lo, c = opens[-k:], highs[-k:], lows[-k:], closes[-k:]
    s = forecast["series"]
    horizon = len(s["mean"])
    total = k + horizon

    y_max = max(max(h), max(s["band_high"]))
    y_min = min(min(lo), min(s["band_low"]))
    pad = (y_max - y_min) * 0.05 or 1.0
    y_max += pad
    y_min -= pad

    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    step = plot_w / total
    body_w = max(1.0, step * 0.6)

    def x(i: float) -> float:
        return _PAD_L + (i + 0.5) * step

    def y(p: float) -> float:
        return _PAD_T + (y_max - p) / (y_max - y_min) * plot_h

    parts: list[str] = []
    # grid + price labels
    for gi in range(6):
        p = y_min + (y_max - y_min) * gi / 5
        yy = y(p)
        parts.append(
            f'<line x1="{_PAD_L}" x2="{_W - _PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>'
            f'<text x="{_W - _PAD_R + 6}" y="{yy + 4:.1f}" class="axis">{_fmt(p)}</text>'
        )
    # history candles
    for i in range(k):
        up = c[i] >= o[i]
        cls = "up" if up else "dn"
        xc = x(i)
        top, bot = y(max(o[i], c[i])), y(min(o[i], c[i]))
        parts.append(
            f'<line x1="{xc:.1f}" x2="{xc:.1f}" y1="{y(h[i]):.1f}" y2="{y(lo[i]):.1f}" class="{cls}"/>'
            f'<rect x="{xc - body_w / 2:.1f}" y="{top:.1f}" width="{body_w:.1f}" '
            f'height="{max(1.0, bot - top):.1f}" class="{cls} body"/>'
        )
    # forecast band + mean line (anchored at last close)
    last = forecast["last_close"]
    xs = [x(k - 1)] + [x(k + j) for j in range(horizon)]
    hi_pts = [last] + s["band_high"]
    lo_pts = [last] + s["band_low"]
    mean_pts = [last] + s["mean"]
    band = " ".join(f"{a:.1f},{y(b):.1f}" for a, b in zip(xs, hi_pts, strict=True))
    band += " " + " ".join(
        f"{a:.1f},{y(b):.1f}" for a, b in reversed(list(zip(xs, lo_pts, strict=True)))
    )
    parts.append(f'<polygon points="{band}" class="band"/>')
    mean_line = " ".join(f"{a:.1f},{y(b):.1f}" for a, b in zip(xs, mean_pts, strict=True))
    parts.append(f'<polyline points="{mean_line}" class="mean"/>')
    # forecast start marker
    xs0 = x(k - 1) + step / 2
    parts.append(
        f'<line x1="{xs0:.1f}" x2="{xs0:.1f}" y1="{_PAD_T}" y2="{_H - _PAD_B}" class="start"/>'
    )
    # labels
    fr = forecast["full_range"]
    mf = forecast["mean_forecast"]
    parts.append(
        f'<text x="{xs[-1]:.1f}" y="{y(s["band_high"][-1]) - 8:.1f}" class="lbl" '
        f'text-anchor="end">en yüksek koşu {_fmt(fr["highest_run"])}</text>'
        f'<text x="{xs[-1]:.1f}" y="{y(s["band_low"][-1]) + 16:.1f}" class="lbl" '
        f'text-anchor="end">en düşük koşu {_fmt(fr["lowest_run"])}</text>'
        f'<rect x="{_W - _PAD_R + 2}" y="{y(last) - 9:.1f}" width="64" height="18" class="tag-last"/>'
        f'<text x="{_W - _PAD_R + 6}" y="{y(last) + 4:.1f}" class="tag-txt">{_fmt(last)}</text>'
        f'<rect x="{_W - _PAD_R + 2}" y="{y(mf["price"]) - 9:.1f}" width="64" height="18" class="tag-mean"/>'
        f'<text x="{_W - _PAD_R + 6}" y="{y(mf["price"]) + 4:.1f}" class="tag-txt dark">{_fmt(mf["price"])}</text>'
    )
    svg = (
        f'<svg viewBox="0 0 {_W} {_H}" preserveAspectRatio="none" role="img" '
        f'aria-label="Mum tahmini grafiği">{"".join(parts)}</svg>'
    )

    cd = forecast["candles"]
    va = forecast["volatility_amplification"]
    n_paths = forecast["n_paths"]
    title = html.escape(symbol or "Mum Tahmini")
    cur = html.escape(currency)
    summary = html.escape(forecast["summary_tr"])
    how = html.escape(forecast["how_it_works"])

    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} Mum Tahmini</title>
<style>
:root {{ --bg:#131722; --panel:#1b2030; --line:#2a3042; --fg:#d1d4dc; --muted:#8a90a2;
  --up:#26a69a; --dn:#ef5350; --acc:#f5a623; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,sans-serif; }}
.wrap {{ display:grid; grid-template-columns:1fr 280px; gap:12px; padding:16px; }}
@media (max-width:900px) {{ .wrap {{ grid-template-columns:1fr; }} }}
.chart {{ background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:8px; }}
.chart h1 {{ font-size:16px; margin:4px 8px 8px; }}
svg {{ width:100%; height:auto; aspect-ratio:{_W}/{_H}; display:block; }}
.grid {{ stroke:var(--line); stroke-width:1; }}
.axis {{ fill:var(--muted); font-size:11px; }}
.up {{ stroke:var(--up); fill:var(--up); }} .dn {{ stroke:var(--dn); fill:var(--dn); }}
.body {{ stroke-width:0; }}
.band {{ fill:var(--acc); fill-opacity:.22; stroke:none; }}
.mean {{ fill:none; stroke:var(--acc); stroke-width:2; }}
.start {{ stroke:var(--dn); stroke-dasharray:4 4; }}
.lbl {{ fill:var(--acc); font-size:11px; }}
.tag-last {{ fill:#2a3042; }} .tag-mean {{ fill:var(--acc); }}
.tag-txt {{ fill:#fff; font-size:11px; }} .tag-txt.dark {{ fill:#111; }}
.note {{ margin:10px 8px 4px; padding:10px 12px; background:var(--panel); border-radius:6px; }}
.side {{ display:flex; flex-direction:column; gap:10px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }}
.card h2 {{ font-size:11px; letter-spacing:.06em; color:var(--muted); margin:0 0 6px; text-transform:uppercase; }}
.big {{ font-size:26px; font-weight:700; }}
.row {{ display:flex; justify-content:space-between; }}
.bar {{ height:6px; border-radius:3px; background:var(--dn); overflow:hidden; margin:6px 0; }}
.bar > span {{ display:block; height:100%; background:var(--up); }}
.amp > span {{ background:var(--acc); }} .amp {{ background:var(--line); }}
.small {{ font-size:12px; color:var(--muted); }}
.acc {{ color:var(--acc); }} .upc {{ color:var(--up); }} .dnc {{ color:var(--dn); }}
</style></head><body>
<div class="wrap">
  <div class="chart">
    <h1>{title} — {n_paths} olası gelecek</h1>
    {svg}
    <div class="note">{summary}</div>
  </div>
  <div class="side">
    <div class="card"><h2>Mumlar</h2>
      <div class="row"><div><span class="small upc">▲ Yukarı</span><div class="big upc">%{cd["up_pct"]}</div></div>
      <div style="text-align:right"><span class="small dnc">Aşağı ▼</span><div class="big dnc">%{cd["down_pct"]}</div></div></div>
      <div class="bar"><span style="width:{cd["up_pct"]}%"></span></div>
      <div class="small"><b>{cd["up_count"]} / {n_paths}</b> koşu son kapanış {cur}{_fmt(last)} üzerinde, <b>{cd["down_count"]} / {n_paths}</b> altında bitti.</div>
    </div>
    <div class="card"><h2>Volatilite artışı</h2>
      <div class="big acc">%{va["pct"]}</div>
      <div class="bar amp"><span style="width:{va["pct"]}%"></span></div>
      <div class="small"><b>{va["count"]} / {n_paths}</b> koşu, sonraki {forecast["horizon"]} mumda son gerçek mumlardan daha sert dalgalanıyor.</div>
    </div>
    <div class="card"><h2>Ortalama tahmin</h2>
      <div class="big acc">{cur}{_fmt(mf["price"])}</div>
      <div class="small">{mf["change_pct"]:+.2f}% ({forecast["horizon"]} mum sonra)</div>
    </div>
    <div class="card"><h2>Tüm aralık</h2>
      <div class="acc"><b>{cur}{_fmt(fr["lowest_run"])} – {cur}{_fmt(fr["highest_run"])}</b></div>
      <div class="small">en düşük → en yüksek koşu</div>
    </div>
    <div class="card"><h2>Nasıl çalışır</h2><div class="small">{how}</div>
      <div class="small" style="margin-top:6px">{html.escape(forecast["disclaimer"])}</div></div>
  </div>
</div>
</body></html>
"""


__all__ = ["render_forecast_html"]
