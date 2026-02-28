"""
APEX SWARM V2 - Main API
Single source FastAPI application
~250 lines | Error handling first | Stateless design
"""

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

import httpx

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr

# ─── CONFIG ────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ─── LOGGING ───────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("apex-swarm")

# ─── DATABASE (SQLite for now, PostgreSQL later) ───────────
import sqlite3

DB_PATH = os.getenv("DATABASE_PATH", "apex_swarm.db")


def get_db():
    """Get database connection with error handling."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(status_code=500, detail="Database unavailable")


def init_db():
    """Initialize database tables."""
    try:
        conn = get_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                license_key TEXT NOT NULL,
                api_key TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                user_api_key TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                result TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (user_api_key) REFERENCES users(api_key)
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database init failed: {e}")
        raise


# ─── MODELS ────────────────────────────────────────────────

class ActivateRequest(BaseModel):
    email: EmailStr
    license_key: str


class DeployRequest(BaseModel):
    agent_type: str  # research, arbitrage, defi
    task_description: str


# ─── AUTH ──────────────────────────────────────────────────

def verify_api_key(request: Request) -> str:
    """Verify API key from header. Fail fast if missing/invalid."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return api_key


# ─── LIFESPAN ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("APEX SWARM started")
    yield
    logger.info("APEX SWARM shutdown")


# ─── APP ──────────────────────────────────────────────────

app = FastAPI(
    title="APEX SWARM",
    version="2.0.0",
    lifespan=lifespan,
)


# ─── PAGES (HTML embedded in FastAPI) ─────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing_page():
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APEX SWARM</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e8e6e3;min-height:100vh;display:flex;align-items:center;justify-content:center}
    .container{max-width:600px;text-align:center;padding:40px}.title{font-size:3rem;font-weight:800;background:linear-gradient(135deg,#4ECDC4,#7B68EE);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:16px}
    .subtitle{color:#888;font-size:1.1rem;margin-bottom:32px}.btn{display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#4ECDC4,#7B68EE);color:#0a0a0f;font-weight:700;text-decoration:none;border-radius:8px;font-size:1rem;transition:opacity 0.2s}.btn:hover{opacity:0.9}</style>
    </head><body><div class="container"><h1 class="title">APEX SWARM</h1><p class="subtitle">Autonomous AI Agent Platform</p><a href="/activate" class="btn">Activate Now →</a></div></body></html>"""


@app.get("/activate", response_class=HTMLResponse)
async def activate_page():
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Activate - APEX SWARM</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e8e6e3;min-height:100vh;display:flex;align-items:center;justify-content:center}
    .card{background:#111118;border:1px solid #222;border-radius:16px;padding:40px;max-width:420px;width:100%}.title{font-size:1.5rem;font-weight:700;margin-bottom:24px;text-align:center}
    label{display:block;font-size:0.85rem;color:#888;margin-bottom:6px;margin-top:16px}input{width:100%;padding:12px;background:#0a0a0f;border:1px solid #333;border-radius:8px;color:#e8e6e3;font-size:1rem}
    .btn{width:100%;padding:14px;background:linear-gradient(135deg,#4ECDC4,#7B68EE);color:#0a0a0f;font-weight:700;border:none;border-radius:8px;font-size:1rem;cursor:pointer;margin-top:24px;transition:opacity 0.2s}.btn:hover{opacity:0.9}
    .msg{margin-top:16px;padding:12px;border-radius:8px;text-align:center;font-size:0.9rem;display:none}.success{background:#4ECDC420;border:1px solid #4ECDC4;color:#4ECDC4}.error{background:#E8485520;border:1px solid #E84855;color:#E84855}</style>
    </head><body><div class="card"><h1 class="title">Activate APEX SWARM</h1>
    <label>Email</label><input type="email" id="email" placeholder="your@email.com">
    <label>License Key</label><input type="text" id="license" placeholder="Enter your license key">
    <button class="btn" onclick="activate()">Activate →</button>
    <div id="success" class="msg success"></div><div id="error" class="msg error"></div>
    <script>async function activate(){const email=document.getElementById('email').value;const license=document.getElementById('license').value;const s=document.getElementById('success');const e=document.getElementById('error');
    s.style.display='none';e.style.display='none';if(!email||!license){e.textContent='Please fill in all fields';e.style.display='block';return}
    try{const r=await fetch('/api/v1/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,license_key:license})});const d=await r.json();
    if(r.ok){localStorage.setItem('apex_api_key',d.api_key);s.innerHTML='Activated! Your API key: <strong>'+d.api_key.slice(0,16)+'...</strong><br><br><a href="/dashboard" style="color:#4ECDC4">Go to Dashboard →</a>';s.style.display='block'}
    else{e.textContent=d.detail||'Activation failed';e.style.display='block'}}catch(err){e.textContent='Connection error';e.style.display='block'}}</script></div></body></html>"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dashboard - APEX SWARM</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e8e6e3;min-height:100vh;padding:24px}
    .header{display:flex;justify-content:space-between;align-items:center;margin-bottom:32px}.logo{font-size:1.5rem;font-weight:800;background:linear-gradient(135deg,#4ECDC4,#7B68EE);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;max-width:900px;margin:0 auto}
    .card{background:#111118;border:1px solid #222;border-radius:12px;padding:24px}h2{font-size:1.1rem;margin-bottom:16px}
    select,input,textarea{width:100%;padding:10px;background:#0a0a0f;border:1px solid #333;border-radius:8px;color:#e8e6e3;font-size:0.9rem;margin-bottom:12px}
    .btn{width:100%;padding:12px;background:linear-gradient(135deg,#4ECDC4,#7B68EE);color:#0a0a0f;font-weight:700;border:none;border-radius:8px;cursor:pointer;font-size:0.9rem}
    .task{padding:12px;background:#0a0a0f;border:1px solid #222;border-radius:8px;margin-bottom:8px;font-size:0.85rem}
    .status{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600}.running{background:#FF6B3520;color:#FF6B35}.completed{background:#4ECDC420;color:#4ECDC4}.pending{background:#88888820;color:#888}
    @media(max-width:640px){.grid{grid-template-columns:1fr}}</style>
    </head><body><div style="max-width:900px;margin:0 auto"><div class="header"><div class="logo">APEX SWARM</div><div style="color:#888;font-size:0.85rem" id="status">Connecting...</div></div>
    <div class="grid"><div class="card"><h2>Deploy Agent</h2>
    <select id="agentType"><option value="research">Research Agent</option><option value="arbitrage">Arbitrage Agent</option><option value="defi">DeFi Yield Agent</option></select>
    <textarea id="taskDesc" rows="3" placeholder="Describe your task..."></textarea>
    <button class="btn" onclick="deploy()">Deploy Agent →</button></div>
    <div class="card"><h2>Active Tasks</h2><div id="tasks"><div style="color:#555;text-align:center;padding:20px">No tasks yet</div></div></div></div></div>
    <script>const apiKey=localStorage.getItem('apex_api_key');if(!apiKey){window.location.href='/activate'}
    document.getElementById('status').textContent='Connected';document.getElementById('status').style.color='#4ECDC4';
    async function deploy(){const type=document.getElementById('agentType').value;const desc=document.getElementById('taskDesc').value;if(!desc){alert('Enter a task description');return}
    try{const r=await fetch('/api/v1/agents/deploy',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':apiKey},body:JSON.stringify({agent_type:type,task_description:desc})});
    if(r.ok){document.getElementById('taskDesc').value='';loadTasks()}else{const d=await r.json();alert(d.detail||'Deploy failed')}}catch(e){alert('Connection error')}}
    async function loadTasks(){try{const r=await fetch('/api/v1/tasks',{headers:{'X-API-Key':apiKey}});if(r.ok){const d=await r.json();const c=document.getElementById('tasks');
    if(d.tasks.length===0){c.innerHTML='<div style="color:#555;text-align:center;padding:20px">No tasks yet</div>';return}
    c.innerHTML=d.tasks.map(t=>'<div class="task"><div style="display:flex;justify-content:space-between;margin-bottom:6px"><strong>'+t.agent_type+'</strong><span class="status '+t.status+'">'+t.status+'</span></div><div style="color:#888">'+t.task_description+'</div>'+(t.result?'<div style="margin-top:8px;color:#4ECDC4;font-size:0.8rem">'+t.result+'</div>':'')+'</div>').join('')}}catch(e){}}
    loadTasks();setInterval(loadTasks,5000);</script></body></html>"""


# ─── API ENDPOINTS ────────────────────────────────────────

@app.post("/api/v1/activate")
async def activate(req: ActivateRequest):
    """Activate a new user. Returns API key."""
    if not req.email or not req.license_key:
        raise HTTPException(status_code=400, detail="Email and license key required")
    
    conn = get_db()
    
    # Check if already activated
    existing = conn.execute("SELECT api_key FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing:
        conn.close()
        return {"api_key": existing["api_key"], "message": "Already activated"}
    
    # Create new user
    user_id = str(uuid.uuid4())
    api_key = f"apex_{uuid.uuid4().hex[:24]}"
    now = datetime.now(timezone.utc).isoformat()
    
    try:
        conn.execute(
            "INSERT INTO users (id, email, license_key, api_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, req.email, req.license_key, api_key, now),
        )
        conn.commit()
        logger.info(f"User activated: {req.email}")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")
    finally:
        conn.close()
    
    return {"api_key": api_key, "message": "Activated successfully"}


@app.post("/api/v1/agents/deploy")
async def deploy_agent(req: DeployRequest, api_key: str = Depends(verify_api_key)):
    """Deploy an agent. Starts background task execution."""
    valid_types = ["research", "arbitrage", "defi"]
    if req.agent_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Agent type must be one of: {valid_types}")
    
    if not req.task_description.strip():
        raise HTTPException(status_code=400, detail="Task description required")
    
    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO agents (id, user_api_key, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
            (agent_id, api_key, req.agent_type, req.task_description, now),
        )
        conn.commit()
    finally:
        conn.close()
    
    # Background task execution (placeholder - 3 second delay)
    asyncio.create_task(execute_task(agent_id, req.agent_type, req.task_description))
    
    logger.info(f"Agent deployed: {req.agent_type} ({agent_id[:8]})")
    return {"agent_id": agent_id, "status": "running"}


@app.get("/api/v1/tasks")
async def get_tasks(api_key: str = Depends(verify_api_key)):
    """Get all tasks for the authenticated user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM agents WHERE user_api_key = ? ORDER BY created_at DESC LIMIT 50",
            (api_key,),
        ).fetchall()
    finally:
        conn.close()
    
    tasks = [dict(row) for row in rows]
    return {"tasks": tasks}


@app.get("/api/v1/health")
async def health_check():
    """Health check for deployment monitoring."""
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "healthy", "version": "2.0.0", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


# ─── BACKGROUND TASK ──────────────────────────────────────

async def execute_task(agent_id: str, agent_type: str, task_description: str):
    """Execute task using Claude API. Falls back to placeholder if no API key."""
    try:
        if not ANTHROPIC_API_KEY:
            logger.warning("No ANTHROPIC_API_KEY set — using placeholder results")
            await asyncio.sleep(3)
            results = {
                "research": "Analysis complete: Found 12 relevant data points. Market sentiment shifted bullish in the last 24h.",
                "arbitrage": "Scan complete: Identified 3 arbitrage opportunities. Best spread: 0.8% on ETH/USDC.",
                "defi": "Yield scan complete: Aave USDC 4.2% APY, Compound ETH 3.8% APY, Curve 3pool 5.1% APY.",
            }
            result = results.get(agent_type, "Task completed")
        else:
            system_prompts = {
                "research": "You are a crypto research analyst. Provide actionable insights with specific data. Max 3 paragraphs.",
                "arbitrage": "You are a crypto arbitrage scanner. Identify opportunities across DEXes/CEXes with pairs, spreads, platforms. Max 3 paragraphs.",
                "defi": "You are a DeFi yield analyst. Identify best yield farming and lending opportunities with protocols, APYs, risk levels. Max 3 paragraphs.",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 1024,
                        "system": system_prompts.get(agent_type, "You are a helpful AI assistant."),
                        "messages": [{"role": "user", "content": task_description}],
                    },
                )
            if response.status_code != 200:
                logger.error(f"Claude API error ({response.status_code}): {response.text[:200]}")
                result = f"Agent error: Claude API returned {response.status_code}"
            else:
                data = response.json()
                result = data["content"][0]["text"]

        conn = get_db()
        try:
            conn.execute(
                "UPDATE agents SET status = 'completed', result = ?, completed_at = ? WHERE id = ?",
                (result, datetime.now(timezone.utc).isoformat(), agent_id),
            )
            conn.commit()
            logger.info(f"Task completed: {agent_id[:8]}")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Task execution failed ({agent_id[:8]}): {e}")
        conn = get_db()
        try:
            conn.execute("UPDATE agents SET status = 'failed', result = ? WHERE id = ?", (str(e), agent_id))
            conn.commit()
        finally:
            conn.close()
