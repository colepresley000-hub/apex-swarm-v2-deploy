import os
import re
import requests

API_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/deploy/sync"
API_KEY = os.getenv("APEX_API_KEY")

# Read multi_model.py as text
with open("multi_model.py", "r") as f:
    content = f.read()

# Extract model keys using regex
# This captures strings like "claude-haiku-4-5" or "claude-opus-4-6"
models_to_test = re.findall(r'"(claude[-\w\d]+)"\s*:', content)
models_to_test = list(set(models_to_test))  # remove duplicates

for model in models_to_test:
    payload = {
        "agent_type": "research",
        "task_description": "Test model connectivity: What is 1+1?",
        "model_override": model
    }
    headers = {
        "X-Api-Key": API_KEY,
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        print(f"Model: {model} → Status: {response.status_code} | Result: {response.text[:100]}")
    except Exception as e:
        print(f"Model: {model} → ERROR: {e}")
