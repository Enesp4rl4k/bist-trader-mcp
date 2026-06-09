"""TradingView shape style overrides — consistent PA / EW / position tool colors."""

from __future__ import annotations

import json
from typing import Any

# PA support / resistance horizontals
PA_SUPPORT_LINE: dict[str, Any] = {
    "linecolor": "#00897B",
    "linewidth": 2,
    "linestyle": 0,
    "showLabel": True,
    "textcolor": "#E0F2F1",
    "fontsize": 11,
}

PA_RANGE_HIGH: dict[str, Any] = {
    "linecolor": "#42A5F5",
    "linewidth": 2,
    "linestyle": 0,
    "showLabel": True,
    "textcolor": "#E3F2FD",
    "fontsize": 10,
}

PA_RANGE_LOW: dict[str, Any] = {
    "linecolor": "#42A5F5",
    "linewidth": 2,
    "linestyle": 0,
    "showLabel": True,
    "textcolor": "#E3F2FD",
    "fontsize": 10,
}

PA_RANGE_MID: dict[str, Any] = {
    "linecolor": "#64B5F6",
    "linewidth": 1,
    "linestyle": 2,
    "showLabel": True,
    "textcolor": "#BBDEFB",
    "fontsize": 9,
}

PA_FVG_LINE: dict[str, Any] = {
    "linecolor": "#7E57C2",
    "linewidth": 1,
    "linestyle": 2,
    "showLabel": True,
    "textcolor": "#EDE7F6",
    "fontsize": 10,
}

PA_RESIST_LINE: dict[str, Any] = {
    "linecolor": "#FF7043",
    "linewidth": 2,
    "linestyle": 0,
    "showLabel": True,
    "textcolor": "#FFF3E0",
    "fontsize": 11,
}

# Elliott wave pivots — neutral dashed (readable on dark/light charts)
EW_TREND_LINE: dict[str, Any] = {
    "linecolor": "#90A4AE",
    "linewidth": 1,
    "linestyle": 2,
    "extendLeft": False,
    "extendRight": False,
}

EW_PROJECTED_LINE: dict[str, Any] = {
    "linecolor": "#FFB74D",
    "linewidth": 2,
    "linestyle": 2,
    "extendLeft": False,
    "extendRight": False,
}

EW_PROJECTED_LABEL: dict[str, Any] = {
    "color": "#FFE082",
    "fontsize": 12,
    "bold": True,
    "backgroundColor": "#E65100",
    "backgroundTransparency": 20,
    "borderColor": "#FFB74D",
}

EW_POINT_LABEL: dict[str, Any] = {
    "color": "#ECEFF1",
    "fontsize": 11,
    "bold": False,
    "backgroundColor": "#455A64",
    "backgroundTransparency": 25,
    "borderColor": "#90A4AE",
}

PA_BANNER_TEXT: dict[str, Any] = {
    "color": "#ECEFF1",
    "fontsize": 12,
    "bold": True,
    "backgroundColor": "#263238",
    "backgroundTransparency": 10,
    "borderColor": "#00897B",
}

POSITION_LONG: dict[str, Any] = {
    "fillBackground": True,
    "fillLabelBackground": True,
    "drawBorder": True,
    "borderColor": "#43A047",
    "profitBackground": "#2E7D32",
    "profitBackgroundTransparency": 72,
    "stopBackground": "#C62828",
    "stopBackgroundTransparency": 72,
    "linecolor": "#66BB6A",
    "linewidth": 2,
}

POSITION_SHORT: dict[str, Any] = {
    "fillBackground": True,
    "fillLabelBackground": True,
    "drawBorder": True,
    "borderColor": "#E53935",
    "profitBackground": "#2E7D32",
    "profitBackgroundTransparency": 72,
    "stopBackground": "#C62828",
    "stopBackgroundTransparency": 72,
    "linecolor": "#EF5350",
    "linewidth": 2,
}


def overrides_json(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def position_tool_overrides(direction: str) -> str:
    base = POSITION_LONG if direction == "long" else POSITION_SHORT
    return overrides_json(base)
