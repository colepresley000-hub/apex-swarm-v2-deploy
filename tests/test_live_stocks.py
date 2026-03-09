from agents.live_stock_agent import stock_summary_agent, send_to_telegram

symbols = ["AAPL", "TSLA", "GOOG"]

for sym in symbols:
    summary = stock_summary_agent(sym)
    send_to_telegram(summary)
    print(f"{sym} Summary:\n{summary}\n")
