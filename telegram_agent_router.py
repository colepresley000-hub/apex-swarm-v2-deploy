import requests
import time

# -----------------------------
# CONFIG
# -----------------------------
TELEGRAM_BOT_TOKEN = "8140483743:AAHJ2U8-O1Pc541nVzJCJAObZuN2u6Q5Gb4"
TELEGRAM_CHAT_ID = "8140483743"
APEX_API_KEY = "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"

API_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/deploy/sync"

# -----------------------------
# TELEGRAM SENDER
# -----------------------------
def send_to_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message[:4000]
    }

    requests.post(url, data=data)


# -----------------------------
# CALL APEX AGENT
# -----------------------------
def run_agent(agent_type, task):

    headers = {
        "X-Api-Key": APEX_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "agent_type": agent_type,
        "task_description": task
    }

    r = requests.post(API_URL, headers=headers, json=payload)

    if r.status_code == 200:

        result = r.json().get("result","")

        message = f"[{agent_type}]\n\n{result}"

        send_to_telegram(message)

        print("Sent:", agent_type)

    else:

        print("Error:", r.text)


# -----------------------------
# TEST AGENTS
# -----------------------------
if __name__ == "__main__":

    agents = [

        ("research","Summarize Bitcoin market today"),

        ("blog-writer","Write a short crypto market update"),

        ("market-researcher","Give a quick market insight")

    ]

    for agent_type, task in agents:

        run_agent(agent_type, task)

        time.sleep(2)
