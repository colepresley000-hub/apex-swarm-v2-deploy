"""
APEX SWARM v3.0 — Autonomous AI Agent Platform
================================================
FastAPI backend with:
  - 66 agents across 6 categories
  - Smart knowledge retrieval (5-factor relevance scoring)
  - Agent tools: web search, URL fetch, crypto prices, code sandbox
  - Sequential pipelines (6 presets)
  - Multi-agent collaboration (3 templates)
  - Cron-based scheduled execution
  - Premium dashboard with 4-tab layout
  - Telegram bot integration

File: main.py
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# ─── LOGGING ──────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("apex-swarm")

# ─── CONFIG ───────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20241022")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN)
DATABASE_PATH = os.getenv("DATABASE_PATH", "apex_swarm.db")
PORT = int(os.getenv("PORT", "8080"))
VERSION = "3.0.0"

# ─── OPTIONAL MODULE IMPORTS (graceful degradation) ───────

TOOLS_AVAILABLE = False
CHAINS_AVAILABLE = False

try:
    from agent_tools import execute_with_tools, get_tools_for_agent
    TOOLS_AVAILABLE = True
    logger.info("✅ agent_tools loaded — agents have real capabilities")
except ImportError:
    logger.warning("⚠️ agent_tools not found — using legacy single-call mode")

try:
    from agent_chains import (
        PRESET_PIPELINES, COLLAB_TEMPLATES, CRON_PRESETS,
        execute_chain, execute_collaboration,
        parse_cron, cron_matches_now, describe_schedule,
    )
    CHAINS_AVAILABLE = True
    logger.info("✅ agent_chains loaded — pipelines, collabs, scheduling active")
except ImportError:
    PRESET_PIPELINES = {}
    COLLAB_TEMPLATES = {}
    CRON_PRESETS = {}
    logger.warning("⚠️ agent_chains not found — chains/collabs/scheduling disabled")

# Smart knowledge (optional)
SMART_KNOWLEDGE = False
try:
    from smart_knowledge import get_relevant_knowledge, score_knowledge
    SMART_KNOWLEDGE = True
    logger.info("✅ smart_knowledge loaded")
except ImportError:
    logger.warning("⚠️ smart_knowledge not found — using basic knowledge retrieval")


# ─── AGENT DEFINITIONS (66 agents, 6 categories) ─────────

AGENT_CATEGORIES = {
    "Crypto & DeFi": {
        "icon": "🪙",
        "agents": {
            "research": {"name": "Crypto Researcher", "description": "Deep research on any crypto topic, token, or protocol", "system": "You are an expert crypto researcher. Provide thorough, data-driven analysis with specific numbers and sources. Cover fundamentals, recent developments, and market context."},
            "token-analysis": {"name": "Token Analyst", "description": "Tokenomics, utility, and valuation analysis", "system": "You are a token analysis specialist. Evaluate tokenomics (supply, distribution, vesting), utility, team credibility, market positioning, and fair value estimation."},
            "defi": {"name": "DeFi Strategist", "description": "DeFi protocols, yield strategies, and liquidity analysis", "system": "You are a DeFi strategy expert. Analyze protocols, yield opportunities, impermanent loss risks, TVL trends, and optimal farming strategies."},
            "onchain-analyst": {"name": "On-Chain Analyst", "description": "Blockchain data, whale movements, and network metrics", "system": "You are an on-chain analysis expert. Analyze active addresses, transaction volumes, exchange flows, whale movements, and network health metrics."},
            "whale-tracker": {"name": "Whale Tracker", "description": "Large wallet monitoring and smart money tracking", "system": "You are a whale tracking specialist. Monitor large wallet movements, smart money flows, accumulation/distribution patterns, and institutional activity."},
            "portfolio-manager": {"name": "Portfolio Manager", "description": "Portfolio construction, rebalancing, and risk management", "system": "You are a crypto portfolio manager. Provide allocation recommendations, rebalancing strategies, risk management frameworks, and position sizing."},
            "macro-analyst": {"name": "Macro Analyst", "description": "Global macro impact on crypto markets", "system": "You are a macro analyst specializing in crypto. Analyze Fed policy, interest rates, dollar strength, global events, and their impact on digital assets."},
            "nft-analyst": {"name": "NFT Analyst", "description": "NFT market analysis, collections, and trends", "system": "You are an NFT market analyst. Evaluate collections, floor prices, whale activity, cultural trends, and emerging NFT narratives."},
            "smart-contract-auditor": {"name": "Smart Contract Auditor", "description": "Contract security analysis and vulnerability detection", "system": "You are a smart contract security auditor. Analyze code for vulnerabilities, reentrancy, overflow, access control issues, and best practices."},
            "gas-optimizer": {"name": "Gas Optimizer", "description": "Transaction optimization and gas strategy", "system": "You are a gas optimization specialist. Advise on optimal gas strategies, transaction timing, batching, L2 alternatives, and cost reduction."},
            "airdrop-hunter": {"name": "Airdrop Hunter", "description": "Identify potential airdrops and qualifying strategies", "system": "You are an airdrop hunting specialist. Identify potential upcoming airdrops, qualification criteria, optimal farming strategies, and expected timelines."},
        },
    },
    "Coding & Dev": {
        "icon": "💻",
        "agents": {
            "fullstack-dev": {"name": "Fullstack Developer", "description": "End-to-end web application development", "system": "You are a senior fullstack developer. Write clean, production-ready code. Use modern best practices, proper error handling, and clear architecture."},
            "code-reviewer": {"name": "Code Reviewer", "description": "Thorough code review with actionable feedback", "system": "You are an expert code reviewer. Provide detailed, constructive feedback on code quality, patterns, performance, readability, and maintainability."},
            "python-dev": {"name": "Python Developer", "description": "Python specialist for scripts, APIs, and data tools", "system": "You are a Python expert. Write idiomatic, efficient Python with proper typing, error handling, and modern patterns (async, dataclasses, etc.)."},
            "js-dev": {"name": "JavaScript Developer", "description": "Modern JS/TS, React, Node.js development", "system": "You are a JavaScript/TypeScript expert. Write modern, type-safe code using current best practices, frameworks, and tooling."},
            "solidity-dev": {"name": "Solidity Developer", "description": "Smart contract development and EVM programming", "system": "You are a Solidity expert. Write secure, gas-optimized smart contracts following best practices. Consider reentrancy, overflow, and access control."},
            "devops": {"name": "DevOps Engineer", "description": "CI/CD, Docker, Kubernetes, and infrastructure", "system": "You are a DevOps engineer. Help with containerization, CI/CD pipelines, infrastructure as code, monitoring, and deployment strategies."},
            "database-architect": {"name": "Database Architect", "description": "Schema design, query optimization, and data modeling", "system": "You are a database architect. Design efficient schemas, optimize queries, advise on indexing strategies, and choose appropriate database technologies."},
            "security-analyst": {"name": "Security Analyst", "description": "Application security audits and vulnerability assessment", "system": "You are a security analyst. Perform thorough security audits, identify vulnerabilities (OWASP Top 10), and recommend mitigations."},
            "api-architect": {"name": "API Architect", "description": "RESTful and GraphQL API design", "system": "You are an API architect. Design clean, scalable APIs with proper authentication, rate limiting, versioning, and documentation."},
            "mobile-dev": {"name": "Mobile Developer", "description": "iOS, Android, and cross-platform development", "system": "You are a mobile development expert. Build performant, user-friendly mobile apps using modern frameworks and platform best practices."},
            "bot-developer": {"name": "Bot Developer", "description": "Telegram, Discord, and trading bot development", "system": "You are a bot development specialist. Build reliable, efficient bots for messaging platforms and automated trading with proper error handling."},
        },
    },
    "Writing & Content": {
        "icon": "✍️",
        "agents": {
            "blog-writer": {"name": "Blog Writer", "description": "SEO-optimized blog posts and articles", "system": "You are an expert blog writer. Create engaging, well-structured content with SEO headings, compelling hooks, and actionable takeaways."},
            "copywriter": {"name": "Copywriter", "description": "Persuasive marketing copy and ad content", "system": "You are a conversion-focused copywriter. Write compelling headlines, ad copy, landing pages, and CTAs that drive action."},
            "social-media": {"name": "Social Media Manager", "description": "Platform-specific social content and strategy", "system": "You are a social media expert. Create platform-optimized content for Twitter, LinkedIn, Instagram with proper hooks, hashtags, and engagement strategies."},
            "email-writer": {"name": "Email Writer", "description": "Email campaigns, newsletters, and sequences", "system": "You are an email marketing expert. Write high-converting subject lines, compelling body copy, and strategic email sequences."},
            "scriptwriter": {"name": "Scriptwriter", "description": "Video scripts, podcasts, and presentations", "system": "You are a scriptwriter. Create engaging scripts for YouTube, podcasts, and presentations with proper pacing, hooks, and storytelling."},
            "technical-writer": {"name": "Technical Writer", "description": "Documentation, guides, and technical content", "system": "You are a technical writer. Create clear, comprehensive documentation, API guides, tutorials, and technical specifications."},
            "ghostwriter": {"name": "Ghostwriter", "description": "Long-form content in any voice or style", "system": "You are a versatile ghostwriter. Adapt to any voice, tone, or style. Produce polished long-form content that sounds authentic to the target voice."},
            "editor": {"name": "Editor", "description": "Proofreading, restructuring, and content refinement", "system": "You are a professional editor. Improve clarity, flow, grammar, and impact. Provide both line edits and structural suggestions."},
            "seo-writer": {"name": "SEO Content Writer", "description": "Search-optimized content with keyword strategy", "system": "You are an SEO content specialist. Write content optimized for search engines while maintaining readability, authority, and user engagement."},
            "press-release": {"name": "PR Writer", "description": "Press releases and media communications", "system": "You are a PR writing specialist. Create compelling press releases, media pitches, and communications following AP style and industry conventions."},
            "whitepaper-writer": {"name": "Whitepaper Writer", "description": "In-depth whitepapers and research documents", "system": "You are a whitepaper specialist. Create thorough, authoritative documents with proper research, data presentation, and professional formatting."},
        },
    },
    "Data & Research": {
        "icon": "📊",
        "agents": {
            "data-analyst": {"name": "Data Analyst", "description": "Data analysis, visualization, and insights", "system": "You are a data analyst. Analyze datasets, identify trends and patterns, create insights, and recommend data-driven decisions."},
            "market-researcher": {"name": "Market Researcher", "description": "Market sizing, trends, and consumer insights", "system": "You are a market researcher. Analyze market size, growth trends, customer segments, and competitive landscapes with specific data points."},
            "financial-analyst": {"name": "Financial Analyst", "description": "Financial modeling, valuations, and analysis", "system": "You are a financial analyst. Perform valuations, financial modeling, ratio analysis, and investment assessments with rigorous methodology."},
            "trend-analyst": {"name": "Trend Analyst", "description": "Emerging trends, signals, and future forecasting", "system": "You are a trend analyst. Identify emerging signals, analyze adoption curves, social sentiment, and forecast future developments."},
            "competitor-analyst": {"name": "Competitor Analyst", "description": "Competitive intelligence and benchmarking", "system": "You are a competitive intelligence analyst. Map competitor landscapes, analyze strengths/weaknesses, positioning, and strategic moves."},
            "report-writer": {"name": "Report Writer", "description": "Professional research reports and analysis documents", "system": "You are a professional report writer. Create structured, data-rich reports with executive summaries, key findings, and actionable recommendations."},
            "survey-designer": {"name": "Survey Designer", "description": "Research survey design and analysis", "system": "You are a survey research expert. Design effective surveys with proper question types, flow, and methodology. Analyze results statistically."},
            "fact-checker": {"name": "Fact Checker", "description": "Verify claims, sources, and data accuracy", "system": "You are a meticulous fact-checker. Verify claims against reliable sources, identify misinformation, and assess data accuracy and methodology."},
        },
    },
    "Business & Strategy": {
        "icon": "📈",
        "agents": {
            "startup-advisor": {"name": "Startup Advisor", "description": "Startup strategy, fundraising, and growth", "system": "You are a startup advisor with experience across multiple exits. Advise on strategy, fundraising, product-market fit, and scaling."},
            "business-plan": {"name": "Business Plan Writer", "description": "Comprehensive business plans and pitch decks", "system": "You are a business plan specialist. Create thorough business plans with market analysis, financial projections, and go-to-market strategy."},
            "pitch-coach": {"name": "Pitch Coach", "description": "Investor pitch refinement and presentation skills", "system": "You are a pitch coaching expert. Help refine investor pitches, storytelling, slide structure, and delivery for maximum impact."},
            "growth-hacker": {"name": "Growth Hacker", "description": "Growth strategies, experiments, and viral mechanics", "system": "You are a growth hacking expert. Design experiments, viral loops, referral mechanics, and data-driven growth strategies."},
            "product-manager": {"name": "Product Manager", "description": "Product strategy, roadmaps, and user stories", "system": "You are a senior product manager. Define product strategy, create roadmaps, write user stories, and prioritize features based on impact."},
            "legal-advisor": {"name": "Legal Advisor", "description": "Business legal guidance and compliance", "system": "You are a legal advisor for tech/crypto businesses. Provide guidance on structure, compliance, IP, contracts, and regulatory considerations. Note: not legal advice."},
            "hr-consultant": {"name": "HR Consultant", "description": "Hiring, culture, and team building", "system": "You are an HR consultant. Advise on hiring strategies, team building, culture, compensation, and organizational design."},
            "brand-strategist": {"name": "Brand Strategist", "description": "Brand positioning, identity, and messaging", "system": "You are a brand strategist. Develop brand positioning, identity frameworks, messaging hierarchies, and communication strategies."},
            "pricing-strategist": {"name": "Pricing Strategist", "description": "Pricing models, optimization, and monetization", "system": "You are a pricing strategy expert. Design pricing models, analyze willingness-to-pay, optimize monetization, and structure tiers."},
        },
    },
    "Productivity": {
        "icon": "⚡",
        "agents": {
            "task-planner": {"name": "Task Planner", "description": "Break down complex projects into actionable steps", "system": "You are a project planning expert. Break complex goals into structured, actionable task lists with priorities, dependencies, and timelines."},
            "meeting-summarizer": {"name": "Meeting Summarizer", "description": "Extract key points and action items from meetings", "system": "You are a meeting summarization specialist. Extract key decisions, action items, owners, and deadlines from meeting notes or transcripts."},
            "email-assistant": {"name": "Email Assistant", "description": "Draft, reply, and manage email communications", "system": "You are an email communication expert. Draft professional, clear, and effective emails for any context. Match tone to the situation."},
            "decision-helper": {"name": "Decision Helper", "description": "Structured decision-making frameworks", "system": "You are a decision-making facilitator. Use frameworks (pros/cons, SWOT, decision matrix) to help make informed, structured decisions."},
            "learning-coach": {"name": "Learning Coach", "description": "Personalized learning plans and study strategies", "system": "You are a learning optimization expert. Create personalized study plans, explain concepts clearly, and use spaced repetition and active recall techniques."},
            "negotiation-coach": {"name": "Negotiation Coach", "description": "Negotiation strategies and preparation", "system": "You are a negotiation expert. Prepare strategies, BATNA analysis, opening positions, and tactical advice for any negotiation scenario."},
        },
    },
}

# Build flat lookup
AGENTS = {}
AGENT_TO_CATEGORY = {}
for cat_name, cat_data in AGENT_CATEGORIES.items():
    for agent_id, agent_info in cat_data["agents"].items():
        AGENTS[agent_id] = agent_info
        AGENT_TO_CATEGORY[agent_id] = cat_name


# ─── DATABASE ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _get_columns(conn, table: str) -> list[str]:
    """Get column names for a table."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


# Detect which column name the DB uses for the user key.
# v2.1 used "api_key", v3.0 uses "user_api_key". We adapt to whatever exists.
USER_KEY_COL = "user_api_key"  # default for fresh installs


def init_db():
    global USER_KEY_COL
    conn = get_db()
    try:
        # Check if agents table exists and which column name it uses
        existing_cols = _get_columns(conn, "agents")

        if existing_cols:
            # Table exists — detect column name
            if "api_key" in existing_cols and "user_api_key" not in existing_cols:
                USER_KEY_COL = "api_key"
                logger.info("📦 Detected v2.1 schema (api_key column) — adapting")
            else:
                USER_KEY_COL = "user_api_key"
        else:
            # Fresh install — create with v3 schema
            USER_KEY_COL = "user_api_key"

        # Create tables if they don't exist (fresh install)
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                {USER_KEY_COL} TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                result TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                {USER_KEY_COL} TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                content TEXT NOT NULL,
                domain TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.8,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                {USER_KEY_COL} TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                task_description TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                schedule_type TEXT DEFAULT 'single',
                pipeline_id TEXT,
                collab_id TEXT,
                enabled INTEGER DEFAULT 1,
                last_run TEXT,
                next_run TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
            CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled);
        """)

        # Try to create user key indexes (may fail if column name differs, that's OK)
        for stmt in [
            f"CREATE INDEX IF NOT EXISTS idx_agents_user ON agents({USER_KEY_COL})",
            f"CREATE INDEX IF NOT EXISTS idx_knowledge_user ON knowledge({USER_KEY_COL})",
            f"CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules({USER_KEY_COL})",
        ]:
            try:
                conn.execute(stmt)
            except Exception:
                pass

        conn.commit()
        logger.info(f"✅ Database initialized (key column: {USER_KEY_COL})")
    finally:
        conn.close()


# ─── PYDANTIC MODELS ─────────────────────────────────────

class DeployRequest(BaseModel):
    agent_type: str
    task_description: str

class KnowledgeRequest(BaseModel):
    agent_type: str
    content: str
    domain: str = "general"
    confidence: float = 0.8

class ChainRequest(BaseModel):
    pipeline_id: Optional[str] = None
    steps: Optional[list] = None
    task_description: str

class CollabRequest(BaseModel):
    collab_id: Optional[str] = None
    parallel_agents: Optional[list] = None
    synthesizer: Optional[dict] = None
    task_description: str

class ScheduleRequest(BaseModel):
    agent_type: str = "research"
    task_description: str
    schedule: str = "daily"
    schedule_type: str = "single"
    pipeline_id: Optional[str] = None
    collab_id: Optional[str] = None


# ─── AUTH ─────────────────────────────────────────────────

def get_api_key(x_api_key: str = Header(None), authorization: str = Header(None)) -> str:
    """Extract API key from headers. Accepts any non-empty key for now."""
    key = x_api_key or ""
    if not key and authorization:
        key = authorization.replace("Bearer ", "")
    if not key:
        raise HTTPException(status_code=401, detail="API key required. Pass X-Api-Key header.")
    return key


# ─── KNOWLEDGE RETRIEVAL ─────────────────────────────────

def get_knowledge_for_agent(user_api_key: str, agent_type: str, task: str = "") -> str:
    """Get relevant knowledge entries for context injection."""
    conn = get_db()
    try:
        if SMART_KNOWLEDGE and task:
            return get_relevant_knowledge(conn, user_api_key, agent_type, task)

        rows = conn.execute(
            f"SELECT content FROM knowledge WHERE {USER_KEY_COL} = ? AND agent_type = ? ORDER BY created_at DESC LIMIT 10",
            (user_api_key, agent_type),
        ).fetchall()
        if not rows:
            return ""
        entries = [r[0] for r in rows]
        return "\n\n## Relevant Knowledge:\n" + "\n---\n".join(entries)
    finally:
        conn.close()


# ─── CORE EXECUTION ──────────────────────────────────────

async def execute_task(agent_id: str, agent_type: str, task_description: str, user_api_key: str = "system"):
    """Execute a single agent task. Uses tools when available, falls back to single-call."""
    if agent_type not in AGENTS:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE agents SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                (f"Unknown agent type: {agent_type}", datetime.now(timezone.utc).isoformat(), agent_id),
            )
            conn.commit()
        finally:
            conn.close()
        return

    agent = AGENTS[agent_type]
    category = AGENT_TO_CATEGORY.get(agent_type, "Productivity")
    system_prompt = agent["system"]

    # Inject knowledge
    knowledge = get_knowledge_for_agent(user_api_key, agent_type, task_description)
    if knowledge:
        system_prompt += knowledge

    try:
        if TOOLS_AVAILABLE:
            tools = get_tools_for_agent(category)
            result = await execute_with_tools(
                api_key=ANTHROPIC_API_KEY,
                model=CLAUDE_MODEL,
                system_prompt=system_prompt,
                user_message=task_description,
                tools=tools,
                max_turns=5,
            )
        else:
            # Legacy single-call mode
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 2048,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": task_description}],
                    },
                )
            if resp.status_code != 200:
                raise Exception(f"Claude API error: {resp.status_code}")
            data = resp.json()
            result = data["content"][0]["text"]

        # Save result
        conn = get_db()
        try:
            conn.execute(
                "UPDATE agents SET status = 'completed', result = ?, completed_at = ? WHERE id = ?",
                (result, datetime.now(timezone.utc).isoformat(), agent_id),
            )
            conn.commit()
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Task execution failed ({agent_id}): {e}")
        conn = get_db()
        try:
            conn.execute(
                "UPDATE agents SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                (f"Error: {str(e)}", datetime.now(timezone.utc).isoformat(), agent_id),
            )
            conn.commit()
        finally:
            conn.close()


# Wrapper for chains module (it expects execute_fn(agent_id, agent_type, prompt))
async def _chain_execute_fn(agent_id: str, agent_type: str, prompt: str):
    await execute_task(agent_id, agent_type, prompt, user_api_key="chain")


# ─── SCHEDULER BACKGROUND LOOP ───────────────────────────

async def scheduler_loop():
    """Background loop: check schedules every 60 seconds."""
    if not CHAINS_AVAILABLE:
        logger.info("Scheduler disabled — agent_chains not loaded")
        return

    logger.info("🕐 Scheduler loop started")
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc)

            conn = get_db()
            try:
                rows = conn.execute(
                    f"SELECT id, {USER_KEY_COL}, agent_type, task_description, cron_expression, schedule_type, pipeline_id, collab_id FROM schedules WHERE enabled = 1"
                ).fetchall()
            finally:
                conn.close()

            for row in rows:
                sched_id, user_key, agent_type, task_desc, cron_expr, sched_type, pipeline_id, collab_id = row
                try:
                    cron = parse_cron(cron_expr)
                    if not cron_matches_now(cron, now):
                        continue

                    logger.info(f"⏰ Firing schedule {sched_id[:8]} ({sched_type}: {agent_type})")

                    if sched_type == "pipeline" and pipeline_id and pipeline_id in PRESET_PIPELINES:
                        pipeline = PRESET_PIPELINES[pipeline_id]
                        chain_id = str(uuid.uuid4())
                        asyncio.create_task(
                            execute_chain(
                                steps=pipeline["steps"],
                                user_input=task_desc,
                                execute_fn=_chain_execute_fn,
                                db_fn=get_db,
                                api_key_user=user_key,
                                chain_id=chain_id,
                            )
                        )
                    elif sched_type == "collab" and collab_id and collab_id in COLLAB_TEMPLATES:
                        template = COLLAB_TEMPLATES[collab_id]
                        cid = str(uuid.uuid4())
                        asyncio.create_task(
                            execute_collaboration(
                                parallel_agents=template["parallel_agents"],
                                synthesizer=template["synthesizer"],
                                user_input=task_desc,
                                execute_fn=_chain_execute_fn,
                                db_fn=get_db,
                                api_key_user=user_key,
                                collab_id=cid,
                            )
                        )
                    else:
                        agent_id = str(uuid.uuid4())
                        now_str = datetime.now(timezone.utc).isoformat()
                        conn = get_db()
                        try:
                            conn.execute(
                                f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
                                (agent_id, user_key, agent_type, f"[Scheduled] {task_desc}", now_str),
                            )
                            conn.commit()
                        finally:
                            conn.close()
                        asyncio.create_task(execute_task(agent_id, agent_type, task_desc, user_key))

                    # Update last_run
                    conn = get_db()
                    try:
                        conn.execute(
                            "UPDATE schedules SET last_run = ? WHERE id = ?",
                            (now.isoformat(), sched_id),
                        )
                        conn.commit()
                    finally:
                        conn.close()

                except Exception as e:
                    logger.error(f"Schedule {sched_id[:8]} error: {e}")

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")


# ─── TELEGRAM BOT ─────────────────────────────────────────

async def setup_telegram_webhook(base_url: str):
    """Set Telegram webhook to point to our API."""
    if not TELEGRAM_ENABLED:
        return
    try:
        webhook_url = f"{base_url}/api/v1/telegram/webhook"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
                json={"url": webhook_url},
            )
        logger.info(f"Telegram webhook: {resp.json()}")
    except Exception as e:
        logger.error(f"Telegram webhook setup failed: {e}")


async def handle_telegram_message(message: dict):
    """Process incoming Telegram message."""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    if not chat_id or not text:
        return

    # Parse command: /agent_type task or just text (defaults to research)
    if text.startswith("/"):
        parts = text[1:].split(" ", 1)
        agent_type = parts[0].replace("_", "-")
        task = parts[1] if len(parts) > 1 else "Provide a general update."
    else:
        agent_type = "research"
        task = text

    if agent_type == "start":
        await send_telegram(chat_id, "🤖 APEX SWARM v3.0\n\nSend any message for research, or use:\n/agent-type Your task\n\nExamples:\n/crypto-research Analyze ETH\n/blog-writer Write about AI\n/code-reviewer Review my code")
        return

    if agent_type not in AGENTS:
        agent_type = "research"

    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    user_key = f"telegram:{chat_id}"

    conn = get_db()
    try:
        conn.execute(
            f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
            (agent_id, user_key, agent_type, task, now),
        )
        conn.commit()
    finally:
        conn.close()

    await send_telegram(chat_id, f"⚡ {AGENTS[agent_type]['name']} is working...")
    await execute_task(agent_id, agent_type, task, user_key)

    conn = get_db()
    try:
        row = conn.execute("SELECT result, status FROM agents WHERE id = ?", (agent_id,)).fetchone()
    finally:
        conn.close()

    result = row[0] if row else "No result"
    if len(result) > 4000:
        result = result[:4000] + "\n\n[Truncated]"
    await send_telegram(chat_id, result)


async def send_telegram(chat_id: int, text: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


# ─── APP LIFESPAN ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Start scheduler
    scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info(f"🚀 APEX SWARM v{VERSION} starting")
    logger.info(f"   Tools: {'✅' if TOOLS_AVAILABLE else '❌'} | Chains: {'✅' if CHAINS_AVAILABLE else '❌'} | Knowledge: {'✅' if SMART_KNOWLEDGE else '❌'}")
    yield
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass


# ─── FASTAPI APP ──────────────────────────────────────────

app = FastAPI(title="APEX SWARM", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── API ENDPOINTS ────────────────────────────────────────

@app.get("/api/v1/health")
async def health():
    return {
        "status": "healthy",
        "version": VERSION,
        "agents": len(AGENTS),
        "tools": TOOLS_AVAILABLE,
        "chains": CHAINS_AVAILABLE,
        "smart_knowledge": SMART_KNOWLEDGE,
        "telegram": TELEGRAM_ENABLED,
    }


@app.get("/api/v1/agents")
async def list_agent_types():
    """List all available agent types grouped by category."""
    result = {}
    for cat_name, cat_data in AGENT_CATEGORIES.items():
        result[cat_name] = {
            "icon": cat_data["icon"],
            "agents": {
                aid: {"name": a["name"], "description": a["description"]}
                for aid, a in cat_data["agents"].items()
            },
        }
    return result


@app.post("/api/v1/deploy")
async def deploy_agent(req: DeployRequest, api_key: str = Depends(get_api_key)):
    """Deploy a single agent to execute a task."""
    if req.agent_type not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent_type}")

    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
            (agent_id, api_key, req.agent_type, req.task_description, now),
        )
        conn.commit()
    finally:
        conn.close()

    asyncio.create_task(execute_task(agent_id, req.agent_type, req.task_description, api_key))

    return {
        "agent_id": agent_id,
        "agent_type": req.agent_type,
        "agent_name": AGENTS[req.agent_type]["name"],
        "status": "running",
        "message": f"Agent deployed. Poll /api/v1/status/{agent_id} for results.",
    }


@app.get("/api/v1/status/{agent_id}")
async def get_status(agent_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        row = conn.execute(
            f"SELECT id, agent_type, task_description, status, result, created_at, completed_at FROM agents WHERE id = ? AND {USER_KEY_COL} = ?",
            (agent_id, api_key),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "agent_id": row[0],
        "agent_type": row[1],
        "task_description": row[2],
        "status": row[3],
        "result": row[4],
        "created_at": row[5],
        "completed_at": row[6],
    }


@app.get("/api/v1/history")
async def get_history(api_key: str = Depends(get_api_key), limit: int = 20):
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT id, agent_type, task_description, status, result, created_at, completed_at FROM agents WHERE {USER_KEY_COL} = ? ORDER BY created_at DESC LIMIT ?",
            (api_key, limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "agent_id": r[0], "agent_type": r[1], "task_description": r[2],
            "status": r[3], "result": r[4], "created_at": r[5], "completed_at": r[6],
        }
        for r in rows
    ]


# ─── KNOWLEDGE ENDPOINTS ─────────────────────────────────

@app.post("/api/v1/knowledge")
async def add_knowledge(req: KnowledgeRequest, api_key: str = Depends(get_api_key)):
    kid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        conn.execute(
            f"INSERT INTO knowledge (id, {USER_KEY_COL}, agent_type, content, domain, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kid, api_key, req.agent_type, req.content, req.domain, req.confidence, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"knowledge_id": kid, "status": "stored"}


@app.get("/api/v1/knowledge")
async def list_knowledge(api_key: str = Depends(get_api_key), agent_type: str = None):
    conn = get_db()
    try:
        if agent_type:
            rows = conn.execute(
                f"SELECT id, agent_type, content, domain, confidence, created_at FROM knowledge WHERE {USER_KEY_COL} = ? AND agent_type = ? ORDER BY created_at DESC LIMIT 50",
                (api_key, agent_type),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT id, agent_type, content, domain, confidence, created_at FROM knowledge WHERE {USER_KEY_COL} = ? ORDER BY created_at DESC LIMIT 50",
                (api_key,),
            ).fetchall()
    finally:
        conn.close()

    return [
        {"id": r[0], "agent_type": r[1], "content": r[2], "domain": r[3], "confidence": r[4], "created_at": r[5]}
        for r in rows
    ]


# ─── CHAINS / PIPELINES ENDPOINTS ────────────────────────

@app.get("/api/v1/pipelines")
async def list_pipelines():
    if not CHAINS_AVAILABLE:
        return {"pipelines": {}, "message": "Chains module not loaded"}
    return {
        "pipelines": {
            pid: {"name": p["name"], "description": p["description"], "category": p["category"], "steps": len(p["steps"])}
            for pid, p in PRESET_PIPELINES.items()
        }
    }


@app.post("/api/v1/chains/deploy")
async def deploy_chain(req: ChainRequest, api_key: str = Depends(get_api_key)):
    if not CHAINS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Chains module not available")

    chain_id = str(uuid.uuid4())

    if req.pipeline_id and req.pipeline_id in PRESET_PIPELINES:
        steps = PRESET_PIPELINES[req.pipeline_id]["steps"]
        pipeline_name = PRESET_PIPELINES[req.pipeline_id]["name"]
    elif req.steps:
        steps = req.steps
        pipeline_name = "Custom Pipeline"
    else:
        raise HTTPException(status_code=400, detail="Provide pipeline_id or custom steps")

    async def run_chain():
        results = await execute_chain(
            steps=steps,
            user_input=req.task_description,
            execute_fn=lambda aid, atype, prompt: execute_task(aid, atype, prompt, api_key),
            db_fn=get_db,
            api_key_user=api_key,
            chain_id=chain_id,
        )
        # Store chain result as a summary agent entry
        summary = f"Pipeline: {pipeline_name}\nSteps completed: {len([r for r in results if r['status'] == 'completed'])}/{len(results)}\n\n"
        for r in results:
            summary += f"--- Step {r['step']} ({r['agent_type']}) [{r['status']}] ---\n{r['result'][:500] if r['result'] else 'No result'}\n\n"

        conn = get_db()
        try:
            conn.execute(
                f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, result, created_at, completed_at) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?)",
                (chain_id, api_key, "chain", f"[Pipeline] {pipeline_name}: {req.task_description[:200]}", summary, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    asyncio.create_task(run_chain())

    return {
        "chain_id": chain_id,
        "pipeline": pipeline_name,
        "steps": len(steps),
        "status": "running",
        "message": f"Pipeline deployed. Poll /api/v1/status/{chain_id} for results.",
    }


# ─── COLLABORATION ENDPOINTS ─────────────────────────────

@app.get("/api/v1/collabs")
async def list_collabs():
    if not CHAINS_AVAILABLE:
        return {"collabs": {}, "message": "Chains module not loaded"}
    return {
        "collabs": {
            cid: {"name": c["name"], "description": c["description"], "category": c["category"], "agents": len(c["parallel_agents"])}
            for cid, c in COLLAB_TEMPLATES.items()
        }
    }


@app.post("/api/v1/collab/deploy")
async def deploy_collab(req: CollabRequest, api_key: str = Depends(get_api_key)):
    if not CHAINS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Chains module not available")

    collab_id = str(uuid.uuid4())

    if req.collab_id and req.collab_id in COLLAB_TEMPLATES:
        template = COLLAB_TEMPLATES[req.collab_id]
        parallel_agents = template["parallel_agents"]
        synthesizer = template["synthesizer"]
        collab_name = template["name"]
    elif req.parallel_agents and req.synthesizer:
        parallel_agents = req.parallel_agents
        synthesizer = req.synthesizer
        collab_name = "Custom Collaboration"
    else:
        raise HTTPException(status_code=400, detail="Provide collab_id or custom parallel_agents + synthesizer")

    async def run_collab():
        result = await execute_collaboration(
            parallel_agents=parallel_agents,
            synthesizer=synthesizer,
            user_input=req.task_description,
            execute_fn=lambda aid, atype, prompt: execute_task(aid, atype, prompt, api_key),
            db_fn=get_db,
            api_key_user=api_key,
            collab_id=collab_id,
        )

        summary = f"Collaboration: {collab_name}\n\n"
        for i, pr in enumerate(result["parallel_results"]):
            summary += f"--- Agent {i+1} [{pr['status']}] ---\n{pr['result'][:500] if pr['result'] else 'No result'}\n\n"
        summary += f"--- SYNTHESIS [{result['synthesis']['status']}] ---\n{result['synthesis']['result']}"

        conn = get_db()
        try:
            conn.execute(
                f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, result, created_at, completed_at) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?)",
                (collab_id, api_key, "collab", f"[Collab] {collab_name}: {req.task_description[:200]}", summary, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    asyncio.create_task(run_collab())

    return {
        "collab_id": collab_id,
        "collab_name": collab_name,
        "agents": len(parallel_agents),
        "status": "running",
        "message": f"Collaboration deployed. Poll /api/v1/status/{collab_id} for results.",
    }


# ─── SCHEDULE ENDPOINTS ──────────────────────────────────

@app.post("/api/v1/schedules")
async def create_schedule(req: ScheduleRequest, api_key: str = Depends(get_api_key)):
    if not CHAINS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Scheduling not available")

    try:
        cron = parse_cron(req.schedule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sched_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    cron_expr = CRON_PRESETS.get(req.schedule, req.schedule)

    conn = get_db()
    try:
        conn.execute(
            f"INSERT INTO schedules (id, {USER_KEY_COL}, agent_type, task_description, cron_expression, schedule_type, pipeline_id, collab_id, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (sched_id, api_key, req.agent_type, req.task_description, cron_expr, req.schedule_type, req.pipeline_id, req.collab_id, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "schedule_id": sched_id,
        "schedule": describe_schedule(req.schedule),
        "cron": cron_expr,
        "status": "active",
    }


@app.get("/api/v1/schedules")
async def list_schedules(api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT id, agent_type, task_description, cron_expression, schedule_type, pipeline_id, collab_id, enabled, last_run, created_at FROM schedules WHERE {USER_KEY_COL} = ? ORDER BY created_at DESC",
            (api_key,),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r[0], "agent_type": r[1], "task_description": r[2],
            "cron_expression": r[3], "schedule_description": describe_schedule(r[3]) if CHAINS_AVAILABLE else r[3],
            "schedule_type": r[4], "pipeline_id": r[5], "collab_id": r[6],
            "enabled": bool(r[7]), "last_run": r[8], "created_at": r[9],
        }
        for r in rows
    ]


@app.delete("/api/v1/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        cursor = conn.execute(
            f"DELETE FROM schedules WHERE id = ? AND {USER_KEY_COL} = ?",
            (schedule_id, api_key),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Schedule not found")
    finally:
        conn.close()
    return {"status": "deleted"}


@app.put("/api/v1/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        row = conn.execute(
            f"SELECT enabled FROM schedules WHERE id = ? AND {USER_KEY_COL} = ?",
            (schedule_id, api_key),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule not found")
        new_state = 0 if row[0] else 1
        conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (new_state, schedule_id))
        conn.commit()
    finally:
        conn.close()
    return {"enabled": bool(new_state)}


# ─── TELEGRAM WEBHOOK ────────────────────────────────────

@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    if not TELEGRAM_ENABLED:
        return {"ok": True}
    data = await request.json()
    message = data.get("message")
    if message:
        asyncio.create_task(handle_telegram_message(message))
    return {"ok": True}


# ─── PREMIUM DASHBOARD ───────────────────────────────────

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML.replace("__VERSION__", VERSION))


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX SWARM v3</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,500;0,9..144,700;1,9..144,400&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0a0a0f;
  --surface: #12121a;
  --surface2: #1a1a26;
  --border: #2a2a3a;
  --text: #e8e8f0;
  --text2: #9090a8;
  --accent: #7c5cfc;
  --accent2: #5c3cdc;
  --success: #34d399;
  --warning: #fbbf24;
  --danger: #f87171;
  --running: #60a5fa;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: 'DM Sans', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}
.header {
  background: linear-gradient(135deg, var(--surface) 0%, #15152a 100%);
  border-bottom: 1px solid var(--border);
  padding: 20px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo {
  font-family: 'Fraunces', serif;
  font-size: 28px;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent), #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.version {
  font-size: 12px;
  color: var(--text2);
  margin-left: 12px;
  font-weight: 300;
}
.status-badges { display: flex; gap: 8px; }
.badge {
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 500;
}
.badge-on { background: rgba(52,211,153,0.15); color: var(--success); }
.badge-off { background: rgba(248,113,113,0.15); color: var(--danger); }

.auth-bar {
  padding: 12px 32px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: 12px;
  align-items: center;
}
.auth-bar input {
  flex: 1;
  max-width: 400px;
  padding: 8px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
}
.auth-bar input:focus { outline: none; border-color: var(--accent); }

.tabs {
  display: flex;
  gap: 0;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
}
.tab {
  padding: 14px 24px;
  cursor: pointer;
  color: var(--text2);
  font-size: 14px;
  font-weight: 500;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}
.tab:hover { color: var(--text); }
.tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.main { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }
.tab-content { display: none; }
.tab-content.active { display: block; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }

.category-section { margin-bottom: 32px; }
.category-title {
  font-family: 'Fraunces', serif;
  font-size: 20px;
  font-weight: 500;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.2s;
}
.card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(124,92,252,0.1);
}
.card-name {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}
.card-desc {
  color: var(--text2);
  font-size: 13px;
  line-height: 1.5;
}
.card-meta {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text2);
  display: flex;
  gap: 12px;
}

/* Pipeline / Collab cards */
.pipeline-card, .collab-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.2s;
}
.pipeline-card:hover, .collab-card:hover {
  border-color: var(--accent);
}

/* Deploy modal */
.modal-overlay {
  display: none;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.7);
  z-index: 100;
  justify-content: center;
  align-items: center;
}
.modal-overlay.show { display: flex; }
.modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 28px;
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  overflow-y: auto;
}
.modal h2 {
  font-family: 'Fraunces', serif;
  font-size: 22px;
  margin-bottom: 4px;
}
.modal-desc { color: var(--text2); font-size: 13px; margin-bottom: 18px; }
.modal textarea {
  width: 100%;
  padding: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  min-height: 100px;
  resize: vertical;
}
.modal textarea:focus { outline: none; border-color: var(--accent); }

.btn {
  padding: 10px 20px;
  border-radius: 8px;
  border: none;
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-primary {
  background: var(--accent);
  color: white;
}
.btn-primary:hover { background: var(--accent2); }
.btn-ghost {
  background: transparent;
  color: var(--text2);
  border: 1px solid var(--border);
}
.btn-ghost:hover { border-color: var(--text2); }
.btn-sm { padding: 6px 14px; font-size: 12px; }
.btn-danger { background: rgba(248,113,113,0.15); color: var(--danger); }
.btn-danger:hover { background: rgba(248,113,113,0.25); }
.modal-actions { display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end; }

/* Result panel */
.result-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  margin-top: 20px;
  display: none;
}
.result-panel.show { display: block; }
.result-status {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}
.status-running { background: rgba(96,165,250,0.15); color: var(--running); }
.status-completed { background: rgba(52,211,153,0.15); color: var(--success); }
.status-failed { background: rgba(248,113,113,0.15); color: var(--danger); }
.result-text {
  margin-top: 14px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  color: var(--text);
}
.result-text h1, .result-text h2, .result-text h3 { font-family: 'Fraunces', serif; margin: 16px 0 8px; }
.result-text strong { color: var(--accent); }
.result-text code { background: var(--bg); padding: 2px 6px; border-radius: 4px; font-size: 13px; }
.result-text pre {
  background: var(--bg);
  padding: 14px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
}

/* Schedule list */
.schedule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 8px;
}
.schedule-info { flex: 1; }
.schedule-info .sched-agent { font-weight: 600; font-size: 14px; }
.schedule-info .sched-task { color: var(--text2); font-size: 13px; margin-top: 2px; }
.schedule-info .sched-cron { color: var(--accent); font-size: 12px; margin-top: 4px; }
.schedule-actions { display: flex; gap: 8px; align-items: center; }

.toggle-switch {
  position: relative;
  width: 40px;
  height: 22px;
  background: var(--border);
  border-radius: 11px;
  cursor: pointer;
  transition: background 0.2s;
}
.toggle-switch.on { background: var(--accent); }
.toggle-switch::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}
.toggle-switch.on::after { transform: translateX(18px); }

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text2);
}
.empty-state .icon { font-size: 48px; margin-bottom: 12px; }
.empty-state p { font-size: 14px; }

/* Schedule creation form */
.sched-form { margin-bottom: 24px; }
.sched-form .form-row {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
  align-items: center;
}
.sched-form select, .sched-form input {
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
}
.sched-form select:focus, .sched-form input:focus {
  outline: none;
  border-color: var(--accent);
}

@media (max-width: 768px) {
  .header { padding: 16px; }
  .main { padding: 16px; }
  .grid { grid-template-columns: 1fr; }
  .tabs { padding: 0 16px; overflow-x: auto; }
  .tab { padding: 12px 16px; white-space: nowrap; }
}
</style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:baseline;">
    <span class="logo">APEX SWARM</span>
    <span class="version">v__VERSION__</span>
  </div>
  <div class="status-badges" id="statusBadges"></div>
</div>

<div class="auth-bar">
  <input type="password" id="apiKey" placeholder="Enter your API key..." value="">
  <button class="btn btn-primary btn-sm" onclick="checkHealth()">Connect</button>
</div>

<div class="tabs">
  <div class="tab active" data-tab="agents">🤖 Agents</div>
  <div class="tab" data-tab="pipelines">🔗 Pipelines</div>
  <div class="tab" data-tab="collabs">🧠 Collaboration</div>
  <div class="tab" data-tab="scheduled">⏰ Scheduled</div>
</div>

<div class="main">

  <!-- AGENTS TAB -->
  <div class="tab-content active" id="tab-agents">
    <div id="agentGrid"></div>
    <div class="result-panel" id="resultPanel">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <strong id="resultAgent"></strong>
          <span class="result-status" id="resultStatus"></span>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('resultPanel').classList.remove('show')">✕</button>
      </div>
      <div class="result-text" id="resultText"></div>
    </div>
  </div>

  <!-- PIPELINES TAB -->
  <div class="tab-content" id="tab-pipelines">
    <div class="grid" id="pipelineGrid"></div>
    <div class="result-panel" id="pipelineResult">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong id="pipelineResultTitle"></strong>
        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('pipelineResult').classList.remove('show')">✕</button>
      </div>
      <div class="result-text" id="pipelineResultText"></div>
    </div>
  </div>

  <!-- COLLABS TAB -->
  <div class="tab-content" id="tab-collabs">
    <div class="grid" id="collabGrid"></div>
    <div class="result-panel" id="collabResult">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong id="collabResultTitle"></strong>
        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('collabResult').classList.remove('show')">✕</button>
      </div>
      <div class="result-text" id="collabResultText"></div>
    </div>
  </div>

  <!-- SCHEDULED TAB -->
  <div class="tab-content" id="tab-scheduled">
    <div class="sched-form">
      <h3 style="font-family:'Fraunces',serif;margin-bottom:12px;">Create Schedule</h3>
      <div class="form-row">
        <select id="schedAgent"></select>
        <select id="schedFreq">
          <option value="daily">Daily (8 AM UTC)</option>
          <option value="twice-daily">Twice Daily</option>
          <option value="weekly">Weekly (Monday)</option>
          <option value="weekdays">Weekdays</option>
          <option value="hourly">Hourly</option>
          <option value="every-6h">Every 6 Hours</option>
          <option value="every-12h">Every 12 Hours</option>
          <option value="monthly">Monthly</option>
        </select>
      </div>
      <div class="form-row">
        <input type="text" id="schedTask" placeholder="Task description..." style="flex:1;">
        <button class="btn btn-primary btn-sm" onclick="createSchedule()">Create</button>
      </div>
    </div>
    <div id="scheduleList"></div>
  </div>
</div>

<!-- Deploy Modal -->
<div class="modal-overlay" id="deployModal">
  <div class="modal">
    <h2 id="modalTitle"></h2>
    <p class="modal-desc" id="modalDesc"></p>
    <textarea id="modalTask" placeholder="Describe your task..."></textarea>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modalDeploy" onclick="deployFromModal()">Deploy ⚡</button>
    </div>
  </div>
</div>

<script>
const API = '';
let currentDeploy = {};

// ─── Tabs ───
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    if (tab.dataset.tab === 'pipelines') loadPipelines();
    if (tab.dataset.tab === 'collabs') loadCollabs();
    if (tab.dataset.tab === 'scheduled') loadSchedules();
  });
});

function getKey() { return document.getElementById('apiKey').value || 'demo'; }
function headers() { return { 'Content-Type': 'application/json', 'X-Api-Key': getKey() }; }

// ─── Health ───
async function checkHealth() {
  try {
    const r = await fetch(API + '/api/v1/health');
    const d = await r.json();
    const badges = document.getElementById('statusBadges');
    badges.innerHTML = `
      <span class="badge ${d.tools ? 'badge-on' : 'badge-off'}">Tools ${d.tools ? '✓' : '✗'}</span>
      <span class="badge ${d.chains ? 'badge-on' : 'badge-off'}">Chains ${d.chains ? '✓' : '✗'}</span>
      <span class="badge ${d.smart_knowledge ? 'badge-on' : 'badge-off'}">Knowledge ${d.smart_knowledge ? '✓' : '✗'}</span>
      <span class="badge badge-on">${d.agents} Agents</span>
    `;
  } catch(e) { console.error(e); }
}

// ─── Agents Tab ───
async function loadAgents() {
  try {
    const r = await fetch(API + '/api/v1/agents');
    const data = await r.json();
    const grid = document.getElementById('agentGrid');
    let html = '';
    for (const [cat, info] of Object.entries(data)) {
      html += `<div class="category-section"><div class="category-title">${info.icon} ${cat}</div><div class="grid">`;
      for (const [id, agent] of Object.entries(info.agents)) {
        html += `<div class="card" onclick="openDeploy('agent','${id}','${agent.name.replace(/'/g,"\\'")}','${agent.description.replace(/'/g,"\\'")}')">
          <div class="card-name">${agent.name}</div>
          <div class="card-desc">${agent.description}</div>
        </div>`;
      }
      html += '</div></div>';
    }
    grid.innerHTML = html;
    // populate schedule agent dropdown
    const sel = document.getElementById('schedAgent');
    sel.innerHTML = '';
    for (const [cat, info] of Object.entries(data)) {
      for (const [id, agent] of Object.entries(info.agents)) {
        sel.innerHTML += `<option value="${id}">${agent.name}</option>`;
      }
    }
  } catch(e) { console.error(e); }
}

// ─── Pipelines Tab ───
async function loadPipelines() {
  try {
    const r = await fetch(API + '/api/v1/pipelines');
    const data = await r.json();
    const grid = document.getElementById('pipelineGrid');
    if (!data.pipelines || Object.keys(data.pipelines).length === 0) {
      grid.innerHTML = '<div class="empty-state"><div class="icon">🔗</div><p>No pipelines available. Deploy agent_chains.py to enable.</p></div>';
      return;
    }
    let html = '';
    for (const [id, p] of Object.entries(data.pipelines)) {
      html += `<div class="pipeline-card">
        <div class="card-name">${p.name}</div>
        <div class="card-desc">${p.description}</div>
        <div class="card-meta"><span>${p.steps} steps</span><span>${p.category}</span></div>
        <div style="margin-top:12px"><button class="btn btn-primary btn-sm" onclick="openDeploy('pipeline','${id}','${p.name.replace(/'/g,"\\'")}','${p.description.replace(/'/g,"\\'")}')">Deploy Pipeline</button></div>
      </div>`;
    }
    grid.innerHTML = html;
  } catch(e) { console.error(e); }
}

// ─── Collabs Tab ───
async function loadCollabs() {
  try {
    const r = await fetch(API + '/api/v1/collabs');
    const data = await r.json();
    const grid = document.getElementById('collabGrid');
    if (!data.collabs || Object.keys(data.collabs).length === 0) {
      grid.innerHTML = '<div class="empty-state"><div class="icon">🧠</div><p>No collaboration templates available.</p></div>';
      return;
    }
    let html = '';
    for (const [id, c] of Object.entries(data.collabs)) {
      html += `<div class="collab-card">
        <div class="card-name">${c.name}</div>
        <div class="card-desc">${c.description}</div>
        <div class="card-meta"><span>${c.agents} agents</span><span>${c.category}</span></div>
        <div style="margin-top:12px"><button class="btn btn-primary btn-sm" onclick="openDeploy('collab','${id}','${c.name.replace(/'/g,"\\'")}','${c.description.replace(/'/g,"\\'")}')">Deploy Collab</button></div>
      </div>`;
    }
    grid.innerHTML = html;
  } catch(e) { console.error(e); }
}

// ─── Schedules Tab ───
async function loadSchedules() {
  try {
    const r = await fetch(API + '/api/v1/schedules', { headers: headers() });
    const data = await r.json();
    const list = document.getElementById('scheduleList');
    if (!data || data.length === 0) {
      list.innerHTML = '<div class="empty-state"><div class="icon">⏰</div><p>No schedules yet. Create one above.</p></div>';
      return;
    }
    let html = '';
    for (const s of data) {
      html += `<div class="schedule-row">
        <div class="schedule-info">
          <div class="sched-agent">${s.agent_type} ${s.schedule_type !== 'single' ? '(' + s.schedule_type + ')' : ''}</div>
          <div class="sched-task">${s.task_description}</div>
          <div class="sched-cron">${s.schedule_description}${s.last_run ? ' · Last: ' + new Date(s.last_run).toLocaleString() : ''}</div>
        </div>
        <div class="schedule-actions">
          <div class="toggle-switch ${s.enabled ? 'on' : ''}" onclick="toggleSched('${s.id}', this)"></div>
          <button class="btn btn-danger btn-sm" onclick="deleteSched('${s.id}')">✕</button>
        </div>
      </div>`;
    }
    list.innerHTML = html;
  } catch(e) { console.error(e); }
}

async function createSchedule() {
  const body = {
    agent_type: document.getElementById('schedAgent').value,
    task_description: document.getElementById('schedTask').value,
    schedule: document.getElementById('schedFreq').value,
    schedule_type: 'single'
  };
  if (!body.task_description) return alert('Enter a task description');
  await fetch(API + '/api/v1/schedules', { method: 'POST', headers: headers(), body: JSON.stringify(body) });
  document.getElementById('schedTask').value = '';
  loadSchedules();
}

async function toggleSched(id, el) {
  await fetch(API + '/api/v1/schedules/' + id + '/toggle', { method: 'PUT', headers: headers() });
  el.classList.toggle('on');
}

async function deleteSched(id) {
  if (!confirm('Delete this schedule?')) return;
  await fetch(API + '/api/v1/schedules/' + id, { method: 'DELETE', headers: headers() });
  loadSchedules();
}

// ─── Modal / Deploy ───
function openDeploy(type, id, name, desc) {
  currentDeploy = { type, id };
  document.getElementById('modalTitle').textContent = name;
  document.getElementById('modalDesc').textContent = desc;
  document.getElementById('modalTask').value = '';
  document.getElementById('deployModal').classList.add('show');
  document.getElementById('modalTask').focus();
}
function closeModal() { document.getElementById('deployModal').classList.remove('show'); }

async function deployFromModal() {
  const task = document.getElementById('modalTask').value;
  if (!task) return alert('Enter a task description');
  closeModal();

  let endpoint, body, resultPanel, resultTitle, resultText;

  if (currentDeploy.type === 'agent') {
    endpoint = '/api/v1/deploy';
    body = { agent_type: currentDeploy.id, task_description: task };
    resultPanel = 'resultPanel';
  } else if (currentDeploy.type === 'pipeline') {
    endpoint = '/api/v1/chains/deploy';
    body = { pipeline_id: currentDeploy.id, task_description: task };
    resultPanel = 'pipelineResult';
  } else if (currentDeploy.type === 'collab') {
    endpoint = '/api/v1/collab/deploy';
    body = { collab_id: currentDeploy.id, task_description: task };
    resultPanel = 'collabResult';
  }

  try {
    const r = await fetch(API + endpoint, { method: 'POST', headers: headers(), body: JSON.stringify(body) });
    const d = await r.json();
    const id = d.agent_id || d.chain_id || d.collab_id;

    const panel = document.getElementById(resultPanel);
    panel.classList.add('show');

    if (resultPanel === 'resultPanel') {
      document.getElementById('resultAgent').textContent = d.agent_name || currentDeploy.id;
      document.getElementById('resultStatus').textContent = 'Running...';
      document.getElementById('resultStatus').className = 'result-status status-running';
      document.getElementById('resultText').innerHTML = 'Agent is working...';
    } else {
      const titleEl = panel.querySelector('strong');
      const textEl = panel.querySelector('.result-text');
      if (titleEl) titleEl.textContent = d.pipeline || d.collab_name || 'Running...';
      if (textEl) textEl.innerHTML = 'Processing...';
    }

    pollResult(id, resultPanel);
  } catch(e) {
    alert('Deploy failed: ' + e.message);
  }
}

async function pollResult(id, panelId) {
  const maxPolls = 120;
  for (let i = 0; i < maxPolls; i++) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const r = await fetch(API + '/api/v1/status/' + id, { headers: headers() });
      if (!r.ok) continue;
      const d = await r.json();
      if (d.status === 'running') continue;

      if (panelId === 'resultPanel') {
        document.getElementById('resultStatus').textContent = d.status;
        document.getElementById('resultStatus').className = 'result-status status-' + d.status;
        document.getElementById('resultText').innerHTML = renderMarkdown(d.result || 'No result');
      } else {
        const panel = document.getElementById(panelId);
        const textEl = panel.querySelector('.result-text');
        if (textEl) textEl.innerHTML = renderMarkdown(d.result || 'No result');
      }
      return;
    } catch(e) { /* retry */ }
  }
}

function renderMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\n/g, '<br>');
}

// ─── Init ───
checkHealth();
loadAgents();
</script>
</body>
</html>"""


# ─── ENTRYPOINT ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
