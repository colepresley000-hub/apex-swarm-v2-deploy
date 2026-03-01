"""
APEX SWARM V2 - Main API
Single source FastAPI application
Smart Knowledge Retrieval + Premium Dashboard
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

# Config
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MONTHLY_AGENT_LIMIT = int(os.getenv("MONTHLY_AGENT_LIMIT", "20"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Agent Registry - add new agents here, no code changes needed
AGENTS = {
    "research": {"name": "Research Analyst", "category": "Crypto & DeFi", "prompt": "You are a crypto research analyst. Provide actionable insights with specific data points. Max 3 paragraphs."},
    "arbitrage": {"name": "Arbitrage Scanner", "category": "Crypto & DeFi", "prompt": "You are a crypto arbitrage scanner. Identify opportunities across DEXes/CEXes with pairs, spreads, platforms. Max 3 paragraphs."},
    "defi": {"name": "DeFi Yield Analyst", "category": "Crypto & DeFi", "prompt": "You are a DeFi yield analyst. Identify best yield farming and lending opportunities with protocols, APYs, risk levels. Max 3 paragraphs."},
    "token-analysis": {"name": "Token Analyzer", "category": "Crypto & DeFi", "prompt": "You are a token analysis expert. Evaluate tokenomics, utility, team, market position. Include market cap and risk. Max 3 paragraphs."},
    "whale-tracker": {"name": "Whale Tracker", "category": "Crypto & DeFi", "prompt": "You are a whale movement analyst. Analyze large wallet movements and what they signal. Max 3 paragraphs."},
    "code-writer": {"name": "Code Writer", "category": "Coding & Dev", "prompt": "You are an expert software engineer. Write clean, production-ready code with error handling and best practices."},
    "code-reviewer": {"name": "Code Reviewer", "category": "Coding & Dev", "prompt": "You are a senior code reviewer. Find bugs, security issues, performance problems. Give specific actionable feedback."},
    "debugger": {"name": "Debugger", "category": "Coding & Dev", "prompt": "You are an expert debugger. Identify root cause and provide clear fix with corrected code."},
    "api-builder": {"name": "API Builder", "category": "Coding & Dev", "prompt": "You are an API architect. Design RESTful APIs with endpoints, schemas, auth, error handling. Output working code."},
    "database-architect": {"name": "Database Architect", "category": "Coding & Dev", "prompt": "You are a database architect. Design schemas, write queries, optimize performance. Include SQL/NoSQL recommendations."},
    "copywriter": {"name": "Copywriter", "category": "Writing & Content", "prompt": "You are an expert copywriter. Write compelling conversion-focused copy matching brand voice and target audience."},
    "blog-writer": {"name": "Blog Writer", "category": "Writing & Content", "prompt": "You are a blog writer and SEO expert. Write engaging posts with SEO headings, keywords, and CTAs."},
    "email-writer": {"name": "Email Writer", "category": "Writing & Content", "prompt": "You are an email marketing expert. Write effective sequences, outreach, newsletters. Focus on engagement and CTAs."},
    "social-media": {"name": "Social Media Agent", "category": "Writing & Content", "prompt": "You are a social media strategist. Create platform-specific content with hashtags, hooks, engagement strategies."},
    "data-analyst": {"name": "Data Analyst", "category": "Data & Research", "prompt": "You are a senior data analyst. Analyze data, identify trends, calculate metrics, provide actionable insights."},
    "market-researcher": {"name": "Market Researcher", "category": "Data & Research", "prompt": "You are a market research analyst. Analyze trends, competitive landscapes, customer segments, growth opportunities."},
    "report-writer": {"name": "Report Writer", "category": "Data & Research", "prompt": "You are a report writer. Create structured reports with executive summaries, findings, analysis, recommendations."},
    "competitor-analyst": {"name": "Competitor Analyst", "category": "Data & Research", "prompt": "You are a competitive intelligence analyst. Analyze competitors products, pricing, positioning, strengths, weaknesses."},
    "nft-analyst": {"name": "NFT Analyst", "category": "Crypto & DeFi", "prompt": "You are an NFT market analyst. Evaluate collections, floor prices, volume trends, holder distribution. Max 3 paragraphs."},
    "gas-optimizer": {"name": "Gas Optimizer", "category": "Crypto & DeFi", "prompt": "You are a gas optimization expert. Recommend optimal transaction timing and gas-saving strategies. Max 3 paragraphs."},
    "portfolio-manager": {"name": "Portfolio Manager", "category": "Crypto & DeFi", "prompt": "You are a crypto portfolio manager. Analyze allocation, suggest rebalancing, assess risk. Max 3 paragraphs."},
    "onchain-analyst": {"name": "On-Chain Analyst", "category": "Crypto & DeFi", "prompt": "You are an on-chain analyst. Analyze active addresses, transaction volume, exchange flows, network health. Max 3 paragraphs."},
    "smart-contract-auditor": {"name": "Smart Contract Auditor", "category": "Crypto & DeFi", "prompt": "You are a smart contract auditor. Review code for vulnerabilities, reentrancy, access control issues."},
    "macro-analyst": {"name": "Macro Analyst", "category": "Crypto & DeFi", "prompt": "You are a macro analyst. Analyze Fed policy, inflation, bond yields, global events affecting crypto. Max 3 paragraphs."},
    "fullstack-dev": {"name": "Full-Stack Developer", "category": "Coding & Dev", "prompt": "You are a full-stack developer. Build complete features with React, Node.js, Python. Include setup instructions."},
    "devops-engineer": {"name": "DevOps Engineer", "category": "Coding & Dev", "prompt": "You are a DevOps engineer. Help with CI/CD, Docker, Kubernetes, cloud deployment, monitoring. Provide working configs."},
    "security-analyst": {"name": "Security Analyst", "category": "Coding & Dev", "prompt": "You are a cybersecurity analyst. Identify vulnerabilities, recommend security practices, audit auth systems."},
    "mobile-dev": {"name": "Mobile Developer", "category": "Coding & Dev", "prompt": "You are a mobile developer. Build features in React Native, Swift, Kotlin. Fix platform-specific bugs."},
    "python-expert": {"name": "Python Expert", "category": "Coding & Dev", "prompt": "You are a Python expert. Write advanced Python with async, decorators, data processing, ML pipelines. Production-ready."},
    "sql-expert": {"name": "SQL Expert", "category": "Coding & Dev", "prompt": "You are an SQL expert. Write complex queries, optimize performance, design indexes, handle migrations."},
    "landing-page": {"name": "Landing Page Writer", "category": "Writing & Content", "prompt": "You are a landing page expert. Write high-converting copy with headlines, benefits, social proof, CTAs."},
    "technical-writer": {"name": "Technical Writer", "category": "Writing & Content", "prompt": "You are a technical writer. Create clear docs, API docs, READMEs, user guides with code examples."},
    "script-writer": {"name": "Script Writer", "category": "Writing & Content", "prompt": "You are a video script writer. Write scripts for YouTube, TikTok, ads, presentations with hooks and CTAs."},
    "press-release": {"name": "Press Release Writer", "category": "Writing & Content", "prompt": "You are a PR specialist. Write press releases, media pitches, announcements in AP style."},
    "seo-specialist": {"name": "SEO Specialist", "category": "Writing & Content", "prompt": "You are an SEO specialist. Analyze keywords, write meta descriptions, optimize content, recommend link building."},
    "ad-copywriter": {"name": "Ad Copywriter", "category": "Writing & Content", "prompt": "You are a performance ad copywriter. Write Google, Facebook, LinkedIn ad copy with headline variations. Focus on CTR."},
    "grant-writer": {"name": "Grant Writer", "category": "Writing & Content", "prompt": "You are a grant writer. Write compelling proposals, project narratives, funding applications with budgets."},
    "financial-analyst": {"name": "Financial Analyst", "category": "Data & Research", "prompt": "You are a financial analyst. Analyze statements, calculate ratios, build projections. Include specific numbers."},
    "survey-analyst": {"name": "Survey Analyst", "category": "Data & Research", "prompt": "You are a survey analyst. Design surveys, analyze responses, identify trends, calculate statistical significance."},
    "trend-analyst": {"name": "Trend Analyst", "category": "Data & Research", "prompt": "You are a trend analyst. Identify emerging trends using data signals, search trends, social media, market indicators."},
    "pricing-strategist": {"name": "Pricing Strategist", "category": "Data & Research", "prompt": "You are a pricing expert. Analyze positioning, competitor pricing, willingness to pay. Recommend optimal pricing."},
    "unit-economics": {"name": "Unit Economics Analyst", "category": "Data & Research", "prompt": "You are a unit economics expert. Calculate CAC, LTV, payback periods, margins, break-even points."},
    "real-estate-analyst": {"name": "Real Estate Analyst", "category": "Data & Research", "prompt": "You are a real estate analyst. Analyze properties, cap rates, ROI, cash flow. Provide investment analysis."},
    "pitch-deck": {"name": "Pitch Deck Writer", "category": "Business & Strategy", "prompt": "You are a pitch deck specialist. Create investor narratives with problem, solution, market, traction, ask."},
    "business-plan": {"name": "Business Plan Writer", "category": "Business & Strategy", "prompt": "You are a business plan writer. Create plans with executive summary, market analysis, financials, growth strategy."},
    "ops-consultant": {"name": "Operations Consultant", "category": "Business & Strategy", "prompt": "You are an ops consultant. Optimize workflows, reduce costs, improve efficiency, design SOPs."},
    "hr-consultant": {"name": "HR Consultant", "category": "Business & Strategy", "prompt": "You are an HR consultant. Write job descriptions, design interviews, create policies, advise on compensation."},
    "legal-analyst": {"name": "Legal Analyst", "category": "Business & Strategy", "prompt": "You are a legal research analyst. Analyze contracts, compliance, regulatory frameworks. Not legal advice."},
    "product-manager": {"name": "Product Manager", "category": "Business & Strategy", "prompt": "You are a product manager. Write PRDs, prioritize features, define user stories, analyze product metrics."},
    "growth-hacker": {"name": "Growth Hacker", "category": "Business & Strategy", "prompt": "You are a growth expert. Design viral loops, referral programs, A/B tests, acquisition funnels."},
    "customer-success": {"name": "Customer Success Agent", "category": "Business & Strategy", "prompt": "You are a customer success expert. Design onboarding, reduce churn, create retention strategies."},
    "sales-strategist": {"name": "Sales Strategist", "category": "Business & Strategy", "prompt": "You are a sales expert. Design sales processes, write outreach sequences, optimize conversion funnels."},
    "brand-strategist": {"name": "Brand Strategist", "category": "Business & Strategy", "prompt": "You are a brand strategist. Define positioning, voice, messaging frameworks, visual identity guidelines."},
    "tax-analyst": {"name": "Tax Analyst", "category": "Business & Strategy", "prompt": "You are a tax analyst. Analyze tax implications, deductions, entity structures, crypto tax reporting. Not tax advice."},
    "startup-advisor": {"name": "Startup Advisor", "category": "Business & Strategy", "prompt": "You are a startup advisor. Analyze business models, go-to-market strategies, risks, and pivots."},
    "translator": {"name": "Translator", "category": "Productivity", "prompt": "You are a professional translator. Translate accurately preserving tone, context, cultural nuance. All languages."},
    "summarizer": {"name": "Summarizer", "category": "Productivity", "prompt": "You are an expert summarizer. Condense documents into structured summaries. Preserve key points and action items."},
    "meeting-notes": {"name": "Meeting Notes Agent", "category": "Productivity", "prompt": "You are a meeting notes specialist. Create structured notes with decisions, action items, deadlines."},
    "resume-writer": {"name": "Resume Writer", "category": "Productivity", "prompt": "You are a resume writer. Write ATS-optimized resumes with action verbs and quantified achievements."},
    "study-helper": {"name": "Study Helper", "category": "Productivity", "prompt": "You are a study assistant. Create flashcards, study guides, practice questions. Explain complex topics simply."},
    "spreadsheet-expert": {"name": "Spreadsheet Expert", "category": "Productivity", "prompt": "You are a spreadsheet expert. Write formulas, build templates, create pivot tables for Excel/Google Sheets."},
    "prompt-engineer": {"name": "Prompt Engineer", "category": "Productivity", "prompt": "You are a prompt engineering expert. Design and optimize AI prompts for better output quality."},
    "contract-reviewer": {"name": "Contract Reviewer", "category": "Productivity", "prompt": "You are a contract reviewer. Analyze key terms, risks, unusual clauses, missing protections. Not legal advice."},
    "travel-planner": {"name": "Travel Planner", "category": "Productivity", "prompt": "You are a travel planner. Create detailed itineraries with flights, hotels, activities, budgets."},
    "fitness-coach": {"name": "Fitness Coach", "category": "Productivity", "prompt": "You are a fitness coach. Design workouts, meal plans, recovery protocols based on goals and experience."},
}

# ─── LOGGING ───────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("apex-swarm")

# ─── DATABASE (SQLite for now, PostgreSQL later) ───────────
import sqlite3

DB_PATH = os.getenv("DATABASE_PATH", "apex_swarm.db")

# ─── SMART KNOWLEDGE IMPORT ───────────────────────────────
try:
    from smart_knowledge import get_relevant_knowledge, format_knowledge_for_prompt, store_pattern as smart_store_pattern
    SMART_KNOWLEDGE_AVAILABLE = True
    logger.info("Smart knowledge module loaded")
except ImportError:
    SMART_KNOWLEDGE_AVAILABLE = False
    logger.warning("smart_knowledge.py not found — using legacy knowledge retrieval")

# ─── DOMAIN MAPPING ───────────────────────────────────────
CATEGORY_TO_DOMAIN = {
    "Crypto & DeFi": "crypto",
    "Coding & Dev": "coding",
    "Writing & Content": "writing",
    "Data & Research": "data",
    "Business & Strategy": "business",
    "Productivity": "productivity",
}


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
            CREATE TABLE IF NOT EXISTS telegram_users (
                chat_id TEXT PRIMARY KEY,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (api_key) REFERENCES users(api_key)
            );
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                agent_type TEXT NOT NULL,
                pattern TEXT NOT NULL,
                source_task_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                usefulness_score INTEGER DEFAULT 0,
                FOREIGN KEY (source_task_id) REFERENCES agents(id)
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
    agent_type: str
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


def check_monthly_limit(api_key: str):
    conn = get_db()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    count = conn.execute("SELECT COUNT(*) FROM agents WHERE user_api_key = ? AND created_at >= ?", (api_key, month_start)).fetchone()[0]
    conn.close()
    if count >= MONTHLY_AGENT_LIMIT:
        raise HTTPException(status_code=429, detail=f"Monthly limit reached ({MONTHLY_AGENT_LIMIT} agents). Resets on the 1st.")
    return count


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
    version="2.1.0",
    lifespan=lifespan,
)


# ─── PAGES ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing_page():
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APEX SWARM</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e8e6e3;min-height:100vh;display:flex;align-items:center;justify-content:center}
    .container{max-width:600px;text-align:center;padding:40px}.title{font-size:3rem;font-weight:800;background:linear-gradient(135deg,#4ECDC4,#7B68EE);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:16px}
    .subtitle{color:#888;font-size:1.1rem;margin-bottom:32px}.btn{display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#4ECDC4,#7B68EE);color:#0a0a0f;font-weight:700;text-decoration:none;border-radius:8px;font-size:1rem;transition:opacity 0.2s}.btn:hover{opacity:0.9}</style>
    </head><body><div class="container"><h1 class="title">APEX SWARM</h1><p class="subtitle">Autonomous AI Agent Platform</p><a href="/activate" class="btn">Activate Now &rarr;</a></div></body></html>"""


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
    <button class="btn" onclick="activate()">Activate &rarr;</button>
    <div id="success" class="msg success"></div><div id="error" class="msg error"></div>
    <script>async function activate(){const email=document.getElementById('email').value;const license=document.getElementById('license').value;const s=document.getElementById('success');const e=document.getElementById('error');
    s.style.display='none';e.style.display='none';if(!email||!license){e.textContent='Please fill in all fields';e.style.display='block';return}
    try{const r=await fetch('/api/v1/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,license_key:license})});const d=await r.json();
    if(r.ok){localStorage.setItem('apex_api_key',d.api_key);s.innerHTML='Activated! Your API key: <strong>'+d.api_key.slice(0,16)+'...</strong><br><br><a href="/dashboard" style="color:#4ECDC4">Go to Dashboard &rarr;</a>';s.style.display='block'}
    else{e.textContent=d.detail||'Activation failed';e.style.display='block'}}catch(err){e.textContent='Connection error';e.style.display='block'}}</script></div></body></html>"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dashboard - APEX SWARM</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,700;9..144,900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:#07070c;color:#e8e6e3;min-height:100vh;padding:24px 16px}
h1,h2,h3,.logo{font-family:'Fraunces',Georgia,serif}
.logo{font-size:1.6rem;font-weight:900;background:linear-gradient(135deg,#4ECDC4 0%,#7B68EE 50%,#E8485E 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-0.02em}
.header{display:flex;justify-content:space-between;align-items:center;max-width:960px;margin:0 auto 28px}
.conn{font-size:0.8rem;padding:4px 12px;border-radius:99px;border:1px solid #333;color:#888}
.conn.live{border-color:#4ECDC4;color:#4ECDC4}
.conn.live::before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:#4ECDC4;margin-right:6px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.stats-row{display:flex;gap:12px;justify-content:center;margin-bottom:28px;flex-wrap:wrap;max-width:960px;margin-left:auto;margin-right:auto}
.stat{padding:10px 20px;background:linear-gradient(135deg,#111118,#161622);border:1px solid #1e1e2e;border-radius:10px;text-align:center;min-width:110px}
.stat .num{font-family:'Fraunces',serif;font-size:1.5rem;font-weight:700;display:block}
.stat .label{font-size:0.7rem;color:#666;text-transform:uppercase;letter-spacing:0.05em;margin-top:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;max-width:960px;margin:0 auto}
@media(max-width:700px){.grid{grid-template-columns:1fr}.stats-row{gap:8px}.stat{min-width:90px;padding:8px 14px}}
.card{background:#0e0e16;border:1px solid #1a1a2a;border-radius:14px;padding:24px}
.card h2{font-size:1.1rem;font-weight:700;margin-bottom:16px;color:#ccc}
select,textarea{width:100%;padding:11px 14px;background:#0a0a10;border:1px solid #252535;border-radius:10px;color:#e8e6e3;font-family:'Inter',sans-serif;font-size:0.88rem;margin-bottom:12px;transition:border-color 0.2s}
select:focus,textarea:focus{outline:none;border-color:#7B68EE}
.btn{width:100%;padding:13px;background:linear-gradient(135deg,#4ECDC4,#7B68EE);color:#0a0a0f;font-weight:700;border:none;border-radius:10px;cursor:pointer;font-size:0.9rem;transition:transform 0.15s,box-shadow 0.15s;font-family:'Inter',sans-serif}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 20px rgba(78,205,196,0.25)}
.btn:active{transform:translateY(0)}
.task{padding:14px 16px;background:#0a0a12;border:1px solid #1a1a2a;border-radius:10px;margin-bottom:10px;font-size:0.85rem;transition:border-color 0.2s}
.task:hover{border-color:#252540}
.task-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.task-type{font-weight:600;color:#ddd}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing:0.03em}
.running{background:rgba(255,107,53,0.12);color:#FF6B35;border:1px solid rgba(255,107,53,0.25)}
.completed{background:rgba(78,205,196,0.12);color:#4ECDC4;border:1px solid rgba(78,205,196,0.25)}
.failed{background:rgba(232,72,85,0.12);color:#E84855;border:1px solid rgba(232,72,85,0.25)}
.pending{background:rgba(136,136,136,0.12);color:#888;border:1px solid rgba(136,136,136,0.25)}
.task-desc{color:#777;font-size:0.82rem;line-height:1.4}
.task-result{margin-top:10px;padding:12px 14px;background:#0d0d18;border:1px solid #1a1a2a;border-radius:8px;font-size:0.82rem;line-height:1.55;color:#bbb;max-height:300px;overflow-y:auto}
.task-result h1,.task-result h2,.task-result h3{color:#e8e6e3;margin:12px 0 6px;font-family:'Fraunces',serif}
.task-result h1{font-size:1.1rem}.task-result h2{font-size:1rem}.task-result h3{font-size:0.9rem}
.task-result p{margin-bottom:8px}
.task-result ul,.task-result ol{margin:6px 0 6px 20px}
.task-result li{margin-bottom:4px}
.task-result code{background:#161625;padding:1px 5px;border-radius:4px;font-size:0.8rem;color:#7B68EE}
.task-result pre{background:#0a0a14;border:1px solid #222;border-radius:6px;padding:10px;overflow-x:auto;margin:8px 0}
.task-result pre code{background:none;padding:0;color:#ccc}
.task-result strong{color:#e8e6e3}
.task-result a{color:#4ECDC4}
.empty{color:#444;text-align:center;padding:30px;font-size:0.9rem}
.footer{text-align:center;margin-top:32px;font-size:0.7rem;color:#333}
</style>
</head><body>
<div class="header"><div class="logo">APEX SWARM</div><div class="conn" id="status">Connecting...</div></div>
<div class="stats-row" id="swarm-stats">
    <div class="stat"><span class="num" id="st-deployed" style="color:#4ECDC4">-</span><span class="label">Deployed</span></div>
    <div class="stat"><span class="num" id="st-completed" style="color:#7B68EE">-</span><span class="label">Completed</span></div>
    <div class="stat"><span class="num" id="st-users" style="color:#FF6B35">-</span><span class="label">Users</span></div>
    <div class="stat"><span class="num" id="st-types" style="color:#4ECDC4">-</span><span class="label">Agent Types</span></div>
    <div class="stat"><span class="num" id="st-patterns" style="color:#E8E6E3">-</span><span class="label">Patterns</span></div>
</div>
<div class="grid">
    <div class="card">
        <h2>Deploy Agent</h2>
        <select id="agentType"></select>
        <textarea id="taskDesc" rows="4" placeholder="Describe your task..."></textarea>
        <button class="btn" onclick="deploy()">Deploy Agent &rarr;</button>
    </div>
    <div class="card">
        <h2>Active Tasks</h2>
        <div id="tasks"><div class="empty">No tasks yet</div></div>
    </div>
</div>
<div class="footer">APEX SWARM v2.1 &middot; Smart Knowledge Engine</div>
<script>
const apiKey=localStorage.getItem('apex_api_key');
if(!apiKey){window.location.href='/activate'}
const statusEl=document.getElementById('status');statusEl.textContent='Live';statusEl.classList.add('live');

function renderMd(text){
    try{return marked.parse(text)}catch(e){return text.replace(/\\n/g,'<br>')}
}

async function deploy(){
    const type=document.getElementById('agentType').value;
    const desc=document.getElementById('taskDesc').value;
    if(!desc){alert('Enter a task description');return}
    const btn=document.querySelector('.btn');btn.textContent='Deploying...';btn.disabled=true;
    try{
        const r=await fetch('/api/v1/agents/deploy',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':apiKey},body:JSON.stringify({agent_type:type,task_description:desc})});
        if(r.ok){document.getElementById('taskDesc').value='';loadTasks()}else{const d=await r.json();alert(d.detail||'Deploy failed')}
    }catch(e){alert('Connection error')}
    btn.textContent='Deploy Agent \\u2192';btn.disabled=false;
}

async function loadTasks(){
    try{
        const r=await fetch('/api/v1/tasks',{headers:{'X-API-Key':apiKey}});
        if(!r.ok)return;
        const d=await r.json();const c=document.getElementById('tasks');
        if(d.tasks.length===0){c.innerHTML='<div class="empty">No tasks yet</div>';return}
        c.innerHTML=d.tasks.map(t=>{
            let resultHtml='';
            if(t.result){resultHtml='<div class="task-result">'+renderMd(t.result)+'</div>'}
            return '<div class="task"><div class="task-header"><span class="task-type">'+t.agent_type+'</span><span class="badge '+t.status+'">'+t.status+'</span></div><div class="task-desc">'+t.task_description+'</div>'+resultHtml+'</div>'
        }).join('')
    }catch(e){}
}

async function loadAgents(){
    try{
        const r=await fetch("/api/v1/agents");
        if(!r.ok)return;
        const d=await r.json();const s=document.getElementById("agentType");s.innerHTML="";
        for(const[cat,agents]of Object.entries(d.agents)){
            const g=document.createElement("optgroup");g.label=cat;
            agents.forEach(a=>{const o=document.createElement("option");o.value=a.id;o.textContent=a.name;g.appendChild(o)});
            s.appendChild(g)
        }
    }catch(e){}
}

async function loadStats(){
    try{
        const r=await fetch("/api/v1/stats");
        if(!r.ok)return;
        const d=await r.json();
        document.getElementById("st-deployed").textContent=d.total_agents_deployed;
        document.getElementById("st-completed").textContent=d.total_completed;
        document.getElementById("st-users").textContent=d.total_users;
        document.getElementById("st-types").textContent=d.agent_types_active;
        document.getElementById("st-patterns").textContent=d.swarm_intelligence_patterns;
    }catch(e){}
}

loadAgents();loadTasks();loadStats();
setInterval(loadTasks,5000);setInterval(loadStats,10000);
</script></body></html>"""


# ─── API ENDPOINTS ────────────────────────────────────────

@app.post("/api/v1/activate")
async def activate(req: ActivateRequest):
    """Activate a new user. Returns API key."""
    if not req.email or not req.license_key:
        raise HTTPException(status_code=400, detail="Email and license key required")

    conn = get_db()

    existing = conn.execute("SELECT api_key FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing:
        conn.close()
        return {"api_key": existing["api_key"], "message": "Already activated"}

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
    if req.agent_type not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {req.agent_type}")
    check_monthly_limit(api_key)

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


@app.get("/api/v1/stats")
async def get_stats():
    """Real-time platform stats from database."""
    conn = get_db()
    try:
        total_agents_deployed = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        total_completed = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'completed'").fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_deployed = conn.execute("SELECT COUNT(*) FROM agents WHERE created_at LIKE ?", (today + "%",)).fetchone()[0]
        today_completed = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'completed' AND completed_at LIKE ?", (today + "%",)).fetchone()[0]
        agent_types_used = conn.execute("SELECT COUNT(DISTINCT agent_type) FROM agents").fetchone()[0]
        total_patterns = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    finally:
        conn.close()
    return {
        "total_agents_deployed": total_agents_deployed,
        "total_completed": total_completed,
        "total_users": total_users,
        "today_deployed": today_deployed,
        "today_completed": today_completed,
        "agent_types_active": agent_types_used,
        "agent_types_available": len(AGENTS),
        "swarm_intelligence_patterns": total_patterns,
    }


@app.get("/api/v1/agents")
async def list_agents():
    result = {}
    for key, agent in AGENTS.items():
        cat = agent["category"]
        if cat not in result:
            result[cat] = []
        result[cat].append({"id": key, "name": agent["name"]})
    return {"agents": result, "total": len(AGENTS)}


@app.get("/api/v1/health")
async def health_check():
    """Health check for deployment monitoring."""
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "healthy", "version": "2.1.0", "smart_knowledge": SMART_KNOWLEDGE_AVAILABLE, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


# ─── TELEGRAM BOT ─────────────────────────────────────────

async def send_telegram(chat_id: str, text: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096], "parse_mode": "Markdown"},
            )
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        message = data.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()
        if not chat_id or not text:
            return {"ok": True}

        if text == "/start":
            await send_telegram(chat_id, "*APEX SWARM Bot*\nLink your account:\n`/link YOUR_API_KEY`\nThen deploy agents:\n`/deploy research Analyze BTC trends`\nCommands: /agents /status /recent /help")
            return {"ok": True}

        if text == "/help":
            await send_telegram(chat_id, "*Commands:*\n`/link API_KEY` - link account\n`/deploy TYPE task` - deploy agent\n`/agents` - list types\n`/status` - your stats\n`/recent` - last 5 results")
            return {"ok": True}

        if text.startswith("/link "):
            api_key = text[6:].strip()
            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
            if not user:
                conn.close()
                await send_telegram(chat_id, "Invalid API key.")
                return {"ok": True}
            conn.execute("INSERT OR REPLACE INTO telegram_users (chat_id, api_key, created_at) VALUES (?, ?, ?)", (chat_id, api_key, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            await send_telegram(chat_id, "Linked! Deploy agents with /deploy")
            return {"ok": True}

        conn = get_db()
        tg_user = conn.execute("SELECT api_key FROM telegram_users WHERE chat_id = ?", (chat_id,)).fetchone()
        conn.close()
        if not tg_user:
            await send_telegram(chat_id, "Link your account first: /link YOUR_API_KEY")
            return {"ok": True}
        api_key = tg_user[0]

        if text == "/agents":
            cats = {}
            for key, agent in AGENTS.items():
                cat = agent["category"]
                if cat not in cats:
                    cats[cat] = []
                cats[cat].append(f"`{key}` - {agent['name']}")
            msg = "*Available Agents:*\n"
            for cat, items in cats.items():
                msg += f"\n*{cat}:*\n" + "\n".join(items)
            await send_telegram(chat_id, msg)
            return {"ok": True}

        if text == "/status":
            conn = get_db()
            now = datetime.now(timezone.utc)
            ms = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            total = conn.execute("SELECT COUNT(*) FROM agents WHERE user_api_key = ?", (api_key,)).fetchone()[0]
            done = conn.execute("SELECT COUNT(*) FROM agents WHERE user_api_key = ? AND status = 'completed'", (api_key,)).fetchone()[0]
            mo = conn.execute("SELECT COUNT(*) FROM agents WHERE user_api_key = ? AND created_at >= ?", (api_key, ms)).fetchone()[0]
            pats = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            conn.close()
            await send_telegram(chat_id, f"*Your Stats:*\nDeployed: {total}\nCompleted: {done}\nThis month: {mo}/{MONTHLY_AGENT_LIMIT}\nSwarm patterns: {pats}")
            return {"ok": True}

        if text == "/recent":
            conn = get_db()
            rows = conn.execute("SELECT agent_type, status, result FROM agents WHERE user_api_key = ? ORDER BY created_at DESC LIMIT 5", (api_key,)).fetchall()
            conn.close()
            if not rows:
                await send_telegram(chat_id, "No tasks yet.")
                return {"ok": True}
            msg = "*Recent Tasks:*\n\n"
            for r in rows:
                preview = (r[2] or "pending")[:200]
                msg += f"*{r[0]}* ({r[1]})\n{preview}\n\n"
            await send_telegram(chat_id, msg)
            return {"ok": True}

        if text.startswith("/deploy "):
            parts = text[8:].strip().split(" ", 1)
            if len(parts) < 2:
                await send_telegram(chat_id, "Usage: /deploy agent_type Your task description")
                return {"ok": True}
            agent_type = parts[0].lower()
            task_desc = parts[1]
            if agent_type not in AGENTS:
                await send_telegram(chat_id, f"Unknown agent: {agent_type}. Use /agents to see types.")
                return {"ok": True}
            conn = get_db()
            now = datetime.now(timezone.utc)
            ms = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            count = conn.execute("SELECT COUNT(*) FROM agents WHERE user_api_key = ? AND created_at >= ?", (api_key, ms)).fetchone()[0]
            if count >= MONTHLY_AGENT_LIMIT:
                conn.close()
                await send_telegram(chat_id, f"Monthly limit reached ({MONTHLY_AGENT_LIMIT}).")
                return {"ok": True}
            agent_id = str(uuid.uuid4())
            conn.execute("INSERT INTO agents (id, user_api_key, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)", (agent_id, api_key, agent_type, task_desc, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            await send_telegram(chat_id, f"Deploying *{AGENTS[agent_type]['name']}*...\nTask: {task_desc[:100]}")
            asyncio.create_task(execute_task_tg(agent_id, agent_type, task_desc, chat_id))
            return {"ok": True}

        await send_telegram(chat_id, "Unknown command. Try /help")
        return {"ok": True}
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"ok": True}


async def execute_task_tg(agent_id: str, agent_type: str, task_description: str, chat_id: str):
    await execute_task(agent_id, agent_type, task_description)
    conn = get_db()
    row = conn.execute("SELECT status, result FROM agents WHERE id = ?", (agent_id,)).fetchone()
    conn.close()
    if row:
        result = row[1] or "No result"
        await send_telegram(chat_id, f"*{AGENTS[agent_type]['name']}* - {row[0]}\n\n{result[:3500]}")


@app.get("/api/v1/telegram/setup")
async def setup_telegram():
    if not TELEGRAM_BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN not set"}
    webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if webhook_url:
        webhook_url = f"https://{webhook_url}/api/v1/telegram/webhook"
    else:
        return {"error": "No public domain found"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", json={"url": webhook_url})
    return r.json()


# ─── KNOWLEDGE & TASK EXECUTION ───────────────────────────

def store_pattern_legacy(agent_id: str, agent_type: str, result: str):
    """Legacy: store knowledge pattern (used when smart_knowledge.py not available)."""
    try:
        pattern = result[:500] if len(result) > 500 else result
        conn = get_db()
        conn.execute(
            "INSERT INTO knowledge (id, agent_type, pattern, source_task_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), agent_type, pattern, agent_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        logger.info(f"Knowledge stored from {agent_id[:8]}")
    except Exception as e:
        logger.error(f"Failed to store pattern: {e}")


def get_collective_knowledge(agent_type: str, task_description: str = "", limit: int = 5) -> str:
    """Retrieve knowledge — uses smart scoring if available, falls back to legacy."""
    try:
        if SMART_KNOWLEDGE_AVAILABLE and task_description:
            # Smart retrieval: relevance-scored
            agent_category = AGENTS.get(agent_type, {}).get("category", "")
            domain = CATEGORY_TO_DOMAIN.get(agent_category, "")
            conn = get_db()
            cursor = conn.cursor()
            patterns = get_relevant_knowledge(cursor, task_description, domain, limit=limit)
            conn.close()
            if not patterns:
                return ""
            formatted = format_knowledge_for_prompt(patterns)
            return "\n\nCOLLECTIVE SWARM INTELLIGENCE:\n" + formatted
        else:
            # Legacy: chronological retrieval
            conn = get_db()
            rows = conn.execute(
                "SELECT pattern FROM knowledge WHERE agent_type = ? ORDER BY created_at DESC LIMIT ?",
                (agent_type, limit),
            ).fetchall()
            cross = conn.execute(
                "SELECT agent_type, pattern FROM knowledge WHERE agent_type != ? ORDER BY created_at DESC LIMIT ?",
                (agent_type, 3),
            ).fetchall()
            conn.close()
            if not rows and not cross:
                return ""
            knowledge = "\n\nCOLLECTIVE SWARM INTELLIGENCE (learned from previous agents):\n"
            if rows:
                knowledge += "\nRecent findings from " + agent_type + " agents:\n"
                for r in rows:
                    knowledge += "- " + r[0][:200] + "\n"
            if cross:
                knowledge += "\nCross-domain insights:\n"
                for r in cross:
                    knowledge += "- [" + r[0] + "] " + r[1][:150] + "\n"
            return knowledge
    except Exception as e:
        logger.error(f"Failed to retrieve knowledge: {e}")
        return ""


def store_knowledge(agent_id: str, agent_type: str, result: str):
    """Store knowledge pattern — smart or legacy."""
    if SMART_KNOWLEDGE_AVAILABLE:
        try:
            agent_category = AGENTS.get(agent_type, {}).get("category", "")
            domain = CATEGORY_TO_DOMAIN.get(agent_category, "")
            pattern_text = result[:500] if len(result) > 500 else result
            conn = get_db()
            cursor = conn.cursor()
            smart_store_pattern(cursor, pattern_text, domain, agent_type, success=True)
            conn.commit()
            conn.close()
            logger.info(f"Smart knowledge stored from {agent_id[:8]} (domain={domain})")
        except Exception as e:
            logger.warning(f"Smart store failed, falling back to legacy: {e}")
            store_pattern_legacy(agent_id, agent_type, result)
    else:
        store_pattern_legacy(agent_id, agent_type, result)


async def execute_task(agent_id: str, agent_type: str, task_description: str):
    """Execute task using Claude API. Falls back to placeholder if no API key."""
    try:
        if not ANTHROPIC_API_KEY:
            logger.warning("No ANTHROPIC_API_KEY set — using placeholder results")
            await asyncio.sleep(3)
            result = f"[Placeholder] {AGENTS[agent_type]['name']} completed analysis of: {task_description[:100]}"
        else:
            system_prompt = AGENTS.get(agent_type, {}).get("prompt", "You are a helpful AI assistant.")
            # Inject collective knowledge (smart or legacy)
            knowledge = get_collective_knowledge(agent_type, task_description)
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
                        "system": system_prompt + knowledge,
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
            # Store in collective knowledge
            if not result.startswith("[Placeholder]") and not result.startswith("Agent error"):
                store_knowledge(agent_id, agent_type, result)
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
