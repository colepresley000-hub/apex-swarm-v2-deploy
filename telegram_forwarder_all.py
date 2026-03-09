import os
import requests
import json

# ---------------------------
# CONFIGURATION
# ---------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
APEX_KEY = os.getenv("APEX_API_KEY")
API_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/deploy/sync"
AGENTS_LIST_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/agents"

if not BOT_TOKEN or not CHAT_ID or not APEX_KEY:
    raise ValueError("Set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and APEX_API_KEY environment variables")

# ---------------------------
# FUNCTION TO SEND TELEGRAM
# ---------------------------
def send_to_telegram(message: str):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": message}
    )

# ---------------------------
# GET ALL REGISTERED AGENTS
# ---------------------------
def get_all_agents():
    headers = {"X-Api-Key": APEX_KEY}
    resp = requests.get(AGENTS_LIST_URL, headers=headers)
    if resp.status_code == 200:
        agents_data = resp.json().get("agents", [])
        # Use 'type' for API calls
        return [agent["type"] for agent in agents_data]
    else:
        print("Error fetching agent list:", resp.text)
        return []

# ---------------------------
# CALL ANY AGENT AND FORWARD
# ---------------------------
def forward_agent(agent_type: str, task_description: str):
    headers = {"X-Api-Key": APEX_KEY, "Content-Type": "application/json"}
    payload = {"agent_type": agent_type, "task_description": task_description}
    resp = requests.post(API_URL, headers=headers, json=payload)
    if resp.status_code == 200:
        result = resp.json().get("result", "")
        send_to_telegram(f"[{agent_type}] {result}")
        print(f"Forwarded [{agent_type}] → Telegram")
    else:
        print(f"Error calling agent {agent_type}: {resp.text}")

# ---------------------------
# MAIN: AUTOMATICALLY FORWARD ALL AGENTS
# ---------------------------
if __name__ == "__main__":
    agents = get_all_agents()
    print(f"Found {len(agents)} agents. Forwarding outputs...")

    for agent_type in agents:
        # Example generic task — can customize per agent later
        task = f"Hello {agent_type}, send a short test message"
        forward_agent(agent_type, task)
