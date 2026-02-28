"""
APEX SWARM V2 - Main API
Single source FastAPI application
Agent configs as data | Error handling first | Stateless design
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

# ─── CONFIG
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MONTHLY_AGENT_LIMIT = int(os.getenv("MONTHLY_AGENT_LIMIT", "20"))

# ─── AGENT REGISTRY (add new agents here, no code changes needed)
AGENTS = {
    "research": {"name": "Research Analyst", "category": "Crypto & DeFi", "prompt": "You are a crypto research analyst. Analyze the user request and provide actionable insights with specific data points, trends, and market indicators. Be concise, max 3 paragraphs."},
    "arbitrage": {"name": "Arbitrage Scanner", "category": "Crypto & DeFi", "prompt": "You are a crypto arbitrage scanner. Identify potential arbitrage opportunities across DEXes and CEXes. Include specific pairs, spreads, platforms, and estimated profit. Be concise, max 3 paragraphs."},
    "defi": {"name": "DeFi Yield Analyst", "category": "Crypto & DeFi", "prompt": "You are a DeFi yield analyst. Identify the best yield farming, staking, and lending opportunities. Include protocols, APYs, TVL, and risk levels. Be concise, max 3 paragraphs."},
    "token-analysis": {"name": "Token Analyzer", "category": "Crypto & DeFi", "prompt": "You are a token analysis expert. Evaluate tokenomics, utility, team, and market position of any crypto token. Include market cap, volume, and risk assessment. Be concise, max 3 paragraphs."},
    "whale-tracker": {"name": "Whale Tracker", "category": "Crypto & DeFi", "prompt": "You are a whale movement analyst. Analyze large wallet movements, exchange inflows/outflows, and what they signal for market direction. Be concise, max 3 paragraphs."},
    "code-writer": {"name": "Code Writer", "category": "Coding & Dev", "prompt": "You are an expert software engineer. Write clean, production-ready code based on the user requirements. Include error handling, comments, and follow best practices. Output code with brief explanation."},
    "code-reviewer": {"name": "Code Reviewer", "category": "Coding & Dev", "prompt": "You are a senior code reviewer. Analyze the provided code for bugs, security vulnerabilities, performance issues, and best practice violations. Provide specific, actionable feedback."},
    "debugger": {"name": "Debugger", "category": "Coding & Dev", "prompt": "You are an expert debugger. Analyze the error or bug described, identify the root cause, and provide a clear fix with explanation. Be specific and include corrected code."},
    "api-builder": {"name": "API Builder", "category": "Coding & Dev", "prompt": "You are an API architect. Design or build RESTful APIs based on requirements. Include endpoints, request/response schemas, authentication, and error handling. Output working code."},
    "database-architect": {"name": "Database Architect", "category": "Coding & Dev", "prompt": "You are a database architect. Design schemas, write queries, optimize performance, and advise on database choices. Include SQL/NoSQL recommendations with reasoning."},
    "copywriter": {"name": "Copywriter", "category": "Writing & Content", "prompt": "You are an expert copywriter. Write compelling, conversion-focused copy for the specified format (ads, landing pages, emails, social). Match the brand voice and target audience described."},
    "blog-writer": {"name": "Blog Writer", "category": "Writing & Content", "prompt": "You are a professional blog writer and SEO expert. Write engaging, well-structured blog posts with SEO-optimized headings, keywords, and meta descriptions. Include a clear hook and call-to-action."},
    "email-writer": {"name": "Email Writer", "category": "Writing & Content", "prompt": "You are an email marketing expert. Write effective email sequences, cold outreach, newsletters, or transactional emails. Focus on open rates, engagement, and clear CTAs."},
    "social-media": {"name": "Social Media Agent", "category": "Writing & Content", "prompt": "You are a social media strategist. Create platform-specific content (Twitter/X, LinkedIn, Instagram, TikTok) with hashtags, hooks, and engagement strategies. Adapt tone to each platform."},
    "data-analyst": {"name": "Data Analyst", "category": "Data & Research", "prompt": "You are a senior data analyst. Analyze data, identify trends, calculate metrics, and provide actionable insights. Include statistical reasoning and visualization recommendations."},
    "market-researcher": {"name": "Market Researcher", "category": "Data & Research", "prompt": "You are a market research analyst. Analyze market trends, competitive landscapes, customer segments, and growth opportunities. Provide data-backed strategic recommendations."},
    "report-writer": {"name": "Report Writer", "category": "Data & Research", "prompt": "You are a professional report writer. Create structured, data-driven reports with executive summaries, key findings, analysis, and recommendations. Use clear headings and concise language."},
    "competitor-analyst": {"name": "Competitor Analyst", "category": "Data & Research", "prompt": "You are a competitive intelligence analyst. Analyze competitors products, pricing, positioning, strengths, and weaknesses. Provide strategic insights and actionable recommendations."},
}

# ─── LOGGING
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("apex-swarm")

# ─── DATABASE
import sqlite3
DB_PATH = os.getenv("DATABASE_PATH", "apex_swarm.db")

def get_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(status_code=500, detail="Database unavailable")

def init_db():
    try:
        conn = get_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, license_key TEXT NOT NULL,
                api_key TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY, user_api_key TEXT NOT NULL, agent_type TEXT NOT NULL,
                task_description TEXT NOT NULL, status TEXT DEFAULT 'pending', result TEXT,
                created_at TEXT NOT NULL, completed_at TEXT,
                FOREIGN KEY (user_api_key) REFERENCES users(api_key)
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database init failed: {e}")
        raise

class ActivateRequest(BaseModel):
    email: EmailStr
    license_key: str

class DeployRequest(BaseModel):
    agent_type: str
    task_description: str

def verify_api_key(request: Request) -> str:
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(f"APEX SWARM started | {len(AGENTS)} agents available | Limit: {MONTHLY_AGENT_LIMIT}/mo")
    yield
    logger.info("APEX SWARM shutdown")

app = FastAPI(title="APEX SWARM", version="2.1.0", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def landing_page():
    return "<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content=\'width=device-width,initial-scale=1\'><title>APEX SWARM</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e8e6e3;min-height:100vh;display:flex;align-items:center;justify-content:center}.container{max-width:600px;text-align:center;padding:40px}.title{font-size:3rem;font-weight:800;background:linear-gradient(135deg,#4ECDC4,#7B68EE);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:16px}.subtitle{color:#888;font-size:1.1rem;margin-bottom:32px}.btn{display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#4ECDC4,#7B68EE);color:#0a0a0f;font-weight:700;text-decoration:none;border-radius:8px;font-size:1rem;transition:opacity 0.2s}.btn:hover{opacity:0.9}</style></head><body><div class=container><h1 class=title>APEX SWARM</h1><p class=subtitle>Autonomous AI Agent Platform &mdash; " + str(len(AGENTS)) + " agents at your command</p><a href=/activate class=btn>Activate Now &rarr;</a></div></body></html>"
