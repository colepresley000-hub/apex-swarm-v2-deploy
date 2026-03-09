import os
import requests
from apex_agent import run_agent
from agent_tools.fetch_stocks import fetch_stock_price

def stock_summary_agent(symbol: str) -> str:
    """
    Fetch stock price and have Claude summarize it
    """
    price = fetch_stock_price(symbol)
    task = f"The current price of {symbol} is ${price}. Please summarize this stock info in plain language for an investor."

    result = run_agent(
        agent_type="research",
        task_description=task,
        model_override="claude-haiku-4-5"
    )
    return result

def send_to_telegram(message: str):
    """
    Send a message to your Telegram chat
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": message})
