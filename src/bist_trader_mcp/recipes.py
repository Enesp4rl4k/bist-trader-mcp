"""Pine recipe registry + renderer.

The MCP exposes `render_pine_recipe(name, data)` so Claude can ask for a
ready-to-paste Pine v6 script with TR-specific data already substituted in.

The actual paste-into-TradingView step is delegated to
tradesdontlie/tradingview-mcp (`pine_new` + `pine_smart_compile`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from . import pine_recipes as _recipes_pkg


@dataclass(frozen=True)
class RecipeMeta:
    name: str
    filename: str
    description: str
    required_placeholders: tuple[str, ...]


RECIPES: dict[str, RecipeMeta] = {
    "tr_macro_backdrop": RecipeMeta(
        name="tr_macro_backdrop",
        filename="tr_macro_backdrop.pine",
        description=(
            "Overlay TR macro context (TCMB policy rate, corridor, CPI YoY) "
            "and PPK meeting day markers on any chart. Pure snapshot — does "
            "not animate over time."
        ),
        required_placeholders=(
            "POLICY_RATE_PCT",
            "O_NIGHT_LENDING",
            "O_NIGHT_BORROWING",
            "CPI_YOY_PCT",
            "PPK_DATES_JSON",
            "AS_OF_DATE",
        ),
    ),
    "tr_basis_monitor": RecipeMeta(
        name="tr_basis_monitor",
        filename="tr_basis_monitor.pine",
        description=(
            "Cost-of-carry basis monitor: plots futures vs spot fair-value "
            "deviation with a Z-score band, fires alerts when futures are "
            "rich/cheap beyond a threshold. Combine with get_yield_curve to "
            "auto-fill the risk-free rate."
        ),
        required_placeholders=(
            "UNDERLYING_SYMBOL",
            "FUTURES_SYMBOL",
            "RISK_FREE_PCT",
            "DIVIDEND_YIELD_PCT",
            "DAYS_TO_EXPIRY",
            "Z_LOOKBACK",
            "Z_THRESHOLD",
            "AS_OF_DATE",
        ),
    ),
}


def list_recipes() -> list[dict[str, Any]]:
    """Metadata listing for the `list_pine_recipes` tool."""
    return [
        {
            "name": r.name,
            "description": r.description,
            "required_placeholders": list(r.required_placeholders),
        }
        for r in RECIPES.values()
    ]


def _load_template(filename: str) -> str:
    return files(_recipes_pkg).joinpath(filename).read_text(encoding="utf-8")


def render_recipe(name: str, data: dict[str, Any]) -> str:
    """Render a Pine recipe by substituting {{PLACEHOLDER}} tokens.

    The substitution is intentionally a simple string replace rather than
    Jinja — Pine has its own `{}` characters and we want predictable output.

    JSON-style values (arrays/objects) should be pre-serialised by the caller
    or will be coerced via `json.dumps`.
    """
    meta = RECIPES.get(name)
    if meta is None:
        raise KeyError(f"unknown recipe: {name}; known: {list(RECIPES)}")

    missing = [p for p in meta.required_placeholders if p not in data]
    if missing:
        raise ValueError(f"recipe {name} missing placeholders: {missing}")

    body = _load_template(meta.filename)
    for placeholder, value in data.items():
        token = "{{" + placeholder + "}}"
        if isinstance(value, list | dict):
            rendered_value = json.dumps(value)
        else:
            rendered_value = str(value)
        body = body.replace(token, rendered_value)
    return body
