import os
import requests

API_URL = "https://apex-swarm-v2-production.up.railway.app/api/v1/deploy/sync"
API_KEY = os.getenv("APEX_API_KEY")  # or replace with your key temporarily

# List of all models loaded in multi_model.py
models_to_test = [
    "claude-haiku-4-5",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-6",
    "claude-3-haiku-20240307",
    # Add other models from multi_model.py here
]

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
    response = requests.post(API_URL, json=payload, headers=headers)
    print(f"Model: {model} → Status: {response.status_code} | Result: {response.text[:100]}")
