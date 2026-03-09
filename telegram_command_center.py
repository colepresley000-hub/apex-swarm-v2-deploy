#!/usr/bin/env python3
import os
import requests
import time

# -----------------------------
# CONFIGURATION
# -----------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
APEX_API_KEY = os.getenv("APEX_API_KEY")
API_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/deploy/sync"
AGENTS_LIST_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/agents"

# -----------------------------
# STATE
# -----------------------------
last_update_id = None

# -----------------------------
# TELEGRAM FUNCTIONS
# -----------------------------
def get_updates():
    global last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    if last_update_id is not None:
        url += f"?offset={last_update_id + 1}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return {"ok": False}

def send_message(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={"chat_id": chat_id, "text": text}
    )

# -----------------------------
# APEX AGENT FUNCTION
# -----------------------------
def call_apex_agent(agent_type, task_description):
    headers = {"X-Api-Key": APEX_API_KEY, "Content-Type": "application/json"}
    payload = {"agent_type": agent_type, "task_description": task_description}
    try:
        resp = requests.post(API_URL, headers=headers, json=payload)
        if resp.status_code == 200:
            return resp.json().get("result", "")
        else:
            return f"Error: {resp.text}"
    except Exception as e:
        return f"Exception: {e}"

# -----------------------------
# PROCESS INCOMING MESSAGE
# -----------------------------
def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text.startswith("/start"):
        send_message(chat_id, "🚀 Welcome to Apex Command Center!\nUse /agents to see available agents.")

    elif text.startswith("/agents"):
        # Fetch all agents dynamically
        headers = {"X-Api-Key": APEX_API_KEY, "Content-Type": "application/json"}
        resp = requests.get(AGENTS_LIST_URL, headers=headers)
        if resp.status_code == 200:
            agents = resp.json().get("agents", [])
            msg_lines = [f"{a['name']} (/{a['type']})" for a in agents]
            send_message(chat_id, "Available agents:\n" + "\n".join(msg_lines[:50]) + "\n…and more")
        else:
            send_message(chat_id, "Error fetching agents.")

    elif text.startswith("/run"):
        parts = text.split(" ", 1)
        if len(parts) == 2:
            agent_task = parts[1]
            agent_type, _, task = agent_task.partition(" ")
            send_message(chat_id, f"⚙ Running agent '{agent_type}' task: {task}")
            result = call_apex_agent(agent_type, task)
            send_message(chat_id, str(result)[:3500])
        else:
            send_message(chat_id, "❌ Usage: /run <agent_type> <task>")

    elif text.startswith("/swarm"):
        task = text.replace("/swarm", "").strip()
        send_message(chat_id, f"🐝 Swarm executing task: {task}")
        result = call_apex_agent("research", f"Use multiple agents to complete: {task}")
        send_message(chat_id, str(result)[:3500])

    else:
        send_message(chat_id, "❌ Unknown command. Use /start to see options.")

# -----------------------------
# MAIN LOOP
# -----------------------------
print("🚀 Telegram Apex Command Center Running...")

while True:
    updates = get_updates()
    if updates.get("ok"):
        for update in updates.get("result", []):
            last_update_id = update["update_id"]
            if "message" in update:
                process_message(update["message"])
    time.sleep(2)
