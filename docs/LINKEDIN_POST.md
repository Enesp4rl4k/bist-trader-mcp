# LinkedIn Post Draft (English)

Here is a comprehensive LinkedIn post designed for your portfolio. It highlights the engineering architecture, the deterministic technical rules, the AI fusion layer, and the cross-market capabilities.

---

**[Hook]**
I built an open-source AI Trading Assistant using the Model Context Protocol (MCP) that refuses to hallucinate. 

Most "AI trading bots" just feed a chart to an LLM and hope for the best. That leads to hallucinations, bad math, and blown accounts. I wanted to build something built on strict engineering principles—a deterministic rule engine combined with AI orchestration.

So I created the **BIST Trader MCP**, an open-source research assistant for Turkish Markets (BIST/VIOP), Macro (CBRT), and Crypto. It connects any LLM directly to TradingView using a CDP bridge.

Here is how the architecture and analysis pipeline works:

**1️⃣ Technical Layer (Pure Deterministic Math)**
LLMs are terrible at reading geometric chart data. Instead of asking an LLM to "find a setup," I built a pure Python engine that processes raw OHLCV data in milliseconds.
• **Price Action (PA):** Maps out Swing Highs/Lows, Support/Resistance, and Fair Value Gaps (FVG) across multiple timeframes.
• **Elliott Wave:** A strict 5-wave impulse identification algorithm that enforces classic wave rules (Wave 3 cannot be the shortest, Wave 4 cannot overlap Wave 1).
*Zero hallucination. Just pure math.*

**2️⃣ Fundamental & Macro Layer**
The system pulls public API data in the background:
• **CBRT (EVDS):** Policy rates, yield curves, and inflation data.
• **KAP & MKK:** Company disclosures, material events, and foreign ownership ratios.
• **Crypto:** Binance funding rates and open interest.

**3️⃣ The AI Fusion Gate**
This is where the LLM shines. Instead of doing the math, the LLM acts as the Chief Risk Officer. It takes the deterministic Technical Report and the Fundamental Context and passes them through a "Fusion Gate." 
• If PA is bullish but Elliott Wave is bearish, the system flags a **Conflict** and blocks the trade.
• If everything aligns, it generates a full TradingView Pine Script recipe and draws the Long/Short position tool directly on your TradingView Desktop.

**🖼️ What the screenshots show:**
1. **BIST:ASELS:** The system detected a structural conflict between PA and Elliott. It blocked the trade (no forced position box), proving its strict risk management.
2. **OANDA:XAUUSD:** A perfectly mapped 5-wave Elliott sequence with aligned Price Action.
3. **BINANCE:BTCUSDT:** Crypto profile detecting multiple Fair Value Gaps (FVG) with tighter swing logic.
4. **BIST:ASELS (Elliott Detail):** Clean Elliott Wave structures mapped without any UI clutter.

The whole pipeline takes ~30 seconds from a single natural language prompt like *"Analyze ASELS and check KAP disclosures."*

The codebase is fully open-source. Feel free to check out the repo, inspect the algorithms, or run it locally on your machine!

🔗 GitHub: https://github.com/Enesp4rl4k/bist-trader-mcp

#softwareengineering #artificialintelligence #algorithmictrading #python #llm #tradingview #mcp #bist
