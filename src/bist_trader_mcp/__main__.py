"""Allow `python -m bist_trader_mcp` invocation."""

from __future__ import annotations

import asyncio

from .server import run


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
