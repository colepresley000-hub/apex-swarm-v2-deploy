from apex_agent import run_agent
from agent_tools.fetch_stocks import fetch_stock_price
import os
import requests

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

def send_to_slack(message: str):
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if webhook:
        requests.post(webhook, json={"text": message})
