import os, re, requests

API_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/deploy/sync"
API_KEY = os.getenv("APEX_API_KEY")

with open("multi_model.py","r") as f:
    content = f.read()

models_to_test = list(set(re.findall(r'"(claude[-\w\d]+)"\s*:', content)))

for model in models_to_test:
    payload = {
        "agent_type": "research",
        "task_description": "Test model connectivity: What is 1+1?",
        "model_override": model
    }
    headers = {"X-Api-Key": API_KEY, "Content-Type": "application/json"}
    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        print(f"Model: {model} → Status: {response.status_code} | Result: {response.text[:100]}")
    except Exception as e:
        print(f"Model: {model} → ERROR: {e}")
