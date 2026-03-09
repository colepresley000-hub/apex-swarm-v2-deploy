import sys
import os

# Add project root to path so Python can find apex_agent and agents
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from agents.live_stock_agent import stock_summary_agent, send_to_telegram

# Set your stock symbols
symbols = ["AAPL", "TSLA", "GOOG"]

for sym in symbols:
    summary = stock_summary_agent(sym)
    send_to_telegram(summary)
    print(f"{sym} Summary:\n{summary}\n")
