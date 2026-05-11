"""Pine Script recipes — TR-aware indicator templates.

Each recipe is a Pine v6 script body with `{{PLACEHOLDER}}` tokens that the
MCP fills in with live data fetched from TCMB/KAP/VIOP/BIST. The fully
rendered Pine code is returned to the LLM, which can then hand it to
tradesdontlie's `pine_new` + `pine_smart_compile` for execution inside the
user's TradingView Desktop.

Naming convention:
    tr_<theme>.pine

To add a recipe:
    1. Drop the .pine file in this folder.
    2. Add an entry to `RECIPES` in recipes.py with its metadata.
"""
