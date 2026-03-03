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
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
VERSION = "3.4.0"

# ─── OPTIONAL MODULE IMPORTS (graceful degradation) ───────

TOOLS_AVAILABLE = False
CHAINS_AVAILABLE = False
MISSION_CONTROL = False

try:
    from agent_tools import execute_with_tools, get_tools_for_agent, set_mcp_registry, get_mcp_tool_definitions
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

try:
    from mission_control import (
        event_bus, daemon_manager, Event, EventType, DAEMON_PRESETS,
    )
    MISSION_CONTROL = True
    logger.info("✅ mission_control loaded — God-eye, daemons, live feed active")
except ImportError:
    event_bus = None
    daemon_manager = None
    DAEMON_PRESETS = {}
    logger.warning("⚠️ mission_control not found — no real-time events")

# Swarm memory
SWARM_MEMORY = False
swarm_memory = None
try:
    from swarm_memory import SwarmMemory
    SWARM_MEMORY = True
    logger.info("✅ swarm_memory loaded — agents share knowledge")
except ImportError:
    logger.warning("⚠️ swarm_memory not found — no shared agent memory")

# MCP registry + rate limiter
MCP_AVAILABLE = False
mcp_registry = None
rate_limiter = None
tier_enforcer = None
try:
    from mcp_registry import MCPRegistry, RateLimiter, TierEnforcer, MCP_TEMPLATES, rate_limiter as _rl
    MCP_AVAILABLE = True
    rate_limiter = _rl
    logger.info("✅ mcp_registry loaded — dynamic tools, rate limiting active")
except ImportError:
    MCP_TEMPLATES = {}
    logger.warning("⚠️ mcp_registry not found — no dynamic tools or rate limiting")

# Workflow engine
WORKFLOWS_AVAILABLE = False
workflow_engine = None
try:
    from workflow_engine import WorkflowEngine, WORKFLOW_TEMPLATES, TriggerType, ActionType
    WORKFLOWS_AVAILABLE = True
    logger.info("✅ workflow_engine loaded — trigger/condition/action automation active")
except ImportError:
    WORKFLOW_TEMPLATES = {}
    logger.warning("⚠️ workflow_engine not found — no workflow automation")

# Smart knowledge (optional)
SMART_KNOWLEDGE = False
try:
    from smart_knowledge import get_relevant_knowledge, compute_relevance
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
            "yield-hunter": {"name": "Yield Hunter", "description": "Scan DeFi protocols for optimal yield across chains", "system": "You are an autonomous DeFi yield hunting agent. Continuously scan protocols across Ethereum, Solana, Base, Arbitrum, and other chains for the best risk-adjusted yields. Analyze TVL stability, protocol audits, impermanent loss, and smart contract risk. Provide ranked opportunities with entry strategies, expected APY, and exit triggers."},
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
            "mcp-architect": {"name": "MCP Architect", "description": "Design Model Context Protocol servers and agent tool interfaces", "system": "You are an MCP (Model Context Protocol) architecture expert. Design universal adapter layers that normalize any API into a common tool interface for AI agents. Build MCP servers, define tool schemas, handle authentication flows, and create composable agent-native integrations. You understand how to make agents the OS — not another tab to navigate."},
            "agent-orchestrator": {"name": "Agent Orchestrator", "description": "Multi-agent system design, workflows, and coordination", "system": "You are an agent orchestration architect. Design multi-agent systems with parallel execution, shared memory, tool routing, and synthesis patterns. Build agent swarms that collaborate via structured handoffs, debate protocols, and convergence strategies. Expert in frameworks like LangGraph, CrewAI, AutoGen, and custom orchestration pipelines."},
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
            "thread-writer": {"name": "Thread Writer", "description": "Viral Twitter/X threads and long-form social narratives", "system": "You are a viral thread specialist. Craft compelling Twitter/X threads with strong hooks, clear narrative arcs, strategic line breaks, and engagement-driving CTAs. You understand what makes content go viral — contrarian takes, specific numbers, storytelling, and pattern interrupts. Optimize for bookmarks and retweets."},
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
            "web-scraper": {"name": "Web Intelligence Agent", "description": "Extract structured data and insights from websites", "system": "You are a web intelligence specialist. Extract, structure, and analyze data from websites, APIs, and public sources. Parse HTML, navigate paginated results, aggregate data across sources, and deliver clean structured datasets. You turn messy web content into actionable intelligence."},
            "ai-landscape": {"name": "AI Landscape Analyst", "description": "Map AI tools, agents, and emerging tech trends", "system": "You are an AI landscape analyst. Map the rapidly evolving ecosystem of AI agents, tools, frameworks, and startups. Track which agent platforms are gaining traction, analyze GitHub stars and adoption curves, evaluate MCP integrations, and identify emerging patterns in agent-native infrastructure. Provide competitive intelligence for builders in the AI agent space."},
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
            "agent-economy": {"name": "Agent Economy Strategist", "description": "Strategy for the machine-to-machine economy and agent-native businesses", "system": "You are a strategist for the emerging agent economy. Advise on building agent-native businesses — services designed for AI agents as customers, not humans. Analyze opportunities in agent-native payments, agent-native communication, agent-native memory, and API-first infrastructure. You understand that every SaaS category will be rebuilt for agents, and you help founders identify which to build and how to position."},
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
            "automation-builder": {"name": "Automation Builder", "description": "Design no-code/low-code automations and agent workflows", "system": "You are an automation architect. Design workflows connecting APIs, tools, and AI agents using platforms like Make, Zapier, n8n, or custom pipelines. Map triggers, conditions, and actions. Build systems where agents autonomously handle recurring tasks — from data collection to report generation to notifications."},
            "workflow-optimizer": {"name": "Workflow Optimizer", "description": "Analyze and optimize business processes with AI agents", "system": "You are a workflow optimization specialist focused on AI agent integration. Audit existing business processes, identify bottlenecks, and design agent-augmented workflows that reduce manual work by 10x. Map which tasks should be fully autonomous, which need human-in-the-loop, and which need multi-agent collaboration. Create implementation roadmaps for agent adoption."},
            "prompt-engineer": {"name": "Prompt Engineer", "description": "Craft and optimize prompts and system instructions for AI agents", "system": "You are an expert prompt engineer. Design, test, and optimize system prompts, tool definitions, and instruction sets for AI agents and LLMs. You understand token efficiency, chain-of-thought elicitation, few-shot patterns, output formatting, guardrails, and how to get consistent high-quality results from Claude, GPT, and other models. Turn vague requirements into precise, high-performing prompts."},
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


# ─── DATABASE (PostgreSQL with SQLite fallback) ──────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        logger.info("✅ PostgreSQL driver loaded")
    except ImportError:
        USE_POSTGRES = False
        logger.warning("⚠️ psycopg2 not installed — falling back to SQLite")


class PgConnectionWrapper:
    """Wraps psycopg2 connection to behave like SQLite (conn.execute returns cursor with fetchone/fetchall)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        # Convert ? to %s for Postgres
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return cur

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def cursor(self):
        return self._conn.cursor()

    @property
    def autocommit(self):
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, val):
        self._conn.autocommit = val


def get_db():
    if USE_POSTGRES:
        raw = psycopg2.connect(DATABASE_URL)
        raw.autocommit = False
        return PgConnectionWrapper(raw)
    else:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def db_execute(conn, sql, params=None):
    """Execute SQL — wrapper handles Postgres compatibility."""
    return conn.execute(sql, params or ())


def db_fetchone(conn, sql, params=None):
    cur = conn.execute(sql, params or ())
    return cur.fetchone()


def db_fetchall(conn, sql, params=None):
    cur = conn.execute(sql, params or ())
    return cur.fetchall()


USER_KEY_COL = "user_api_key"


def init_db():
    global USER_KEY_COL
    USER_KEY_COL = "user_api_key"
    conn = get_db()
    try:
        if USE_POSTGRES:
            # PostgreSQL schema — use executescript through wrapper
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS knowledge (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
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
                    user_api_key TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS daemon_configs (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    preset_id TEXT,
                    agent_type TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    interval_seconds INTEGER DEFAULT 300,
                    max_cycles INTEGER DEFAULT 0,
                    alert_conditions TEXT DEFAULT '[]',
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS licenses (
                    license_key TEXT PRIMARY KEY,
                    email TEXT,
                    product_id TEXT,
                    tier TEXT DEFAULT 'starter',
                    uses_count INTEGER DEFAULT 0,
                    max_agents INTEGER DEFAULT 5,
                    max_daemons INTEGER DEFAULT 1,
                    active INTEGER DEFAULT 1,
                    validated_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_log (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                );
            """)
            # Indexes
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_agents_user ON agents(user_api_key)",
                "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_user ON knowledge(user_api_key)",
                "CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules(user_api_key)",
                "CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled)",
                "CREATE INDEX IF NOT EXISTS idx_daemon_configs_user ON daemon_configs(user_api_key)",
                "CREATE INDEX IF NOT EXISTS idx_usage_log_user ON usage_log(user_api_key)",
                "CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_licenses_active ON licenses(active)",
            ]:
                try:
                    conn.execute(idx_sql)
                except Exception:
                    pass
            conn.commit()
            logger.info("✅ PostgreSQL database initialized")
        else:
            # SQLite fallback — detect old schema
            try:
                rows = conn.execute("PRAGMA table_info(agents)").fetchall()
                existing_cols = [r[1] for r in rows]
                if "api_key" in existing_cols and "user_api_key" not in existing_cols:
                    USER_KEY_COL = "api_key"
                    logger.info("📦 Detected v2.1 schema (api_key column)")
            except Exception:
                pass

            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    {USER_KEY_COL} TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
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

                CREATE TABLE IF NOT EXISTS daemon_configs (
                    id TEXT PRIMARY KEY,
                    {USER_KEY_COL} TEXT NOT NULL,
                    preset_id TEXT,
                    agent_type TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    interval_seconds INTEGER DEFAULT 300,
                    max_cycles INTEGER DEFAULT 0,
                    alert_conditions TEXT DEFAULT '[]',
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS licenses (
                    license_key TEXT PRIMARY KEY,
                    email TEXT,
                    product_id TEXT,
                    tier TEXT DEFAULT 'starter',
                    uses_count INTEGER DEFAULT 0,
                    max_agents INTEGER DEFAULT 5,
                    max_daemons INTEGER DEFAULT 1,
                    active INTEGER DEFAULT 1,
                    validated_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_log (
                    id TEXT PRIMARY KEY,
                    {USER_KEY_COL} TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
                CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled);
            """)

            for stmt in [
                f"CREATE INDEX IF NOT EXISTS idx_agents_user ON agents({USER_KEY_COL})",
                f"CREATE INDEX IF NOT EXISTS idx_knowledge_user ON knowledge({USER_KEY_COL})",
                f"CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules({USER_KEY_COL})",
                f"CREATE INDEX IF NOT EXISTS idx_daemon_configs_user ON daemon_configs({USER_KEY_COL})",
                f"CREATE INDEX IF NOT EXISTS idx_usage_log_user ON usage_log({USER_KEY_COL})",
            ]:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass

            conn.commit()
            logger.info(f"✅ SQLite database initialized (key column: {USER_KEY_COL})")
    finally:
        conn.close()

    # Initialize swarm memory tables
    if SWARM_MEMORY:
        global swarm_memory
        swarm_memory = SwarmMemory(get_db, db_execute, db_fetchall, db_fetchone, USER_KEY_COL)
        conn = get_db()
        try:
            swarm_memory.init_tables(conn)
            logger.info("✅ Swarm memory tables initialized")
        except Exception as e:
            logger.error(f"Swarm memory init failed: {e}")
        finally:
            conn.close()

    # Initialize MCP registry tables
    if MCP_AVAILABLE:
        global mcp_registry, tier_enforcer
        mcp_registry = MCPRegistry(get_db, db_execute, db_fetchall, db_fetchone, USER_KEY_COL)
        tier_enforcer = TierEnforcer(get_db, db_fetchone, USER_KEY_COL)
        conn = get_db()
        try:
            mcp_registry.init_tables(conn)
            logger.info("✅ MCP registry tables initialized")
            # Wire MCP into agent_tools for dynamic tool execution
            if TOOLS_AVAILABLE:
                set_mcp_registry(mcp_registry)
        except Exception as e:
            logger.error(f"MCP registry init failed: {e}")
        finally:
            conn.close()

    # Initialize workflow engine tables
    if WORKFLOWS_AVAILABLE:
        global workflow_engine
        workflow_engine = WorkflowEngine(get_db, db_execute, db_fetchall, db_fetchone, USER_KEY_COL)
        conn = get_db()
        try:
            workflow_engine.init_tables(conn)
            logger.info("✅ Workflow engine tables initialized")
        except Exception as e:
            logger.error(f"Workflow engine init failed: {e}")
        finally:
            conn.close()


# ─── COST TRACKING ────────────────────────────────────────

# Haiku 4.5 pricing (per 1M tokens)
COST_PER_1M_INPUT = 0.80
COST_PER_1M_OUTPUT = 4.00


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * COST_PER_1M_INPUT / 1_000_000) + (output_tokens * COST_PER_1M_OUTPUT / 1_000_000)


def log_usage(user_api_key: str, agent_type: str, input_tokens: int, output_tokens: int, agent_id: str = None):
    """Log token usage and cost."""
    cost = calculate_cost(input_tokens, output_tokens)
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        uid = str(uuid.uuid4())
        db_execute(conn,
            f"INSERT INTO usage_log (id, {USER_KEY_COL}, agent_type, input_tokens, output_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, user_api_key, agent_type, input_tokens, output_tokens, cost, now),
        )
        # Update agent record if we have the ID
        if agent_id:
            db_execute(conn,
                "UPDATE agents SET input_tokens = ?, output_tokens = ?, cost_usd = ? WHERE id = ?",
                (input_tokens, output_tokens, cost, agent_id),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Usage logging failed: {e}")
    finally:
        conn.close()
    return cost


# ─── GUMROAD LICENSE VALIDATION ──────────────────────────

GUMROAD_PRODUCT_ID = os.getenv("GUMROAD_PRODUCT_ID", "")

# Tier limits
TIER_LIMITS = {
    "free": {"max_agents_per_day": 3, "max_daemons": 0, "max_schedules": 0, "tools": False},
    "starter": {"max_agents_per_day": 25, "max_daemons": 1, "max_schedules": 3, "tools": True},
    "pro": {"max_agents_per_day": 100, "max_daemons": 5, "max_schedules": 10, "tools": True},
    "enterprise": {"max_agents_per_day": 9999, "max_daemons": 50, "max_schedules": 100, "tools": True},
    "admin": {"max_agents_per_day": 99999, "max_daemons": 999, "max_schedules": 999, "tools": True},
}


async def validate_gumroad_license(license_key: str) -> dict:
    """Validate a license key against Gumroad API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.gumroad.com/v2/licenses/verify",
                data={
                    "product_id": GUMROAD_PRODUCT_ID,
                    "license_key": license_key,
                    "increment_uses_count": "false",
                },
            )
        if resp.status_code != 200:
            return {"valid": False, "error": "Gumroad API error"}

        data = resp.json()
        if not data.get("success"):
            return {"valid": False, "error": data.get("message", "Invalid license")}

        purchase = data.get("purchase", {})
        email = purchase.get("email", "")
        variants = purchase.get("variants", "")
        uses = data.get("uses", 0)

        # Determine tier from Gumroad variant or default to starter
        tier = "starter"
        if "pro" in variants.lower():
            tier = "pro"
        elif "enterprise" in variants.lower():
            tier = "enterprise"

        return {"valid": True, "email": email, "tier": tier, "uses": uses}
    except Exception as e:
        logger.error(f"Gumroad validation error: {e}")
        return {"valid": False, "error": str(e)}


async def get_or_validate_license(license_key: str) -> dict:
    """Check DB cache first, then validate with Gumroad."""
    conn = get_db()
    try:
        row = db_fetchone(conn, "SELECT license_key, email, tier, active, validated_at FROM licenses WHERE license_key = ?", (license_key,))
        if row and row[3]:  # active
            return {"valid": True, "email": row[1], "tier": row[2], "cached": True}
    finally:
        conn.close()

    # Not cached or inactive — validate with Gumroad
    if not GUMROAD_PRODUCT_ID:
        # No Gumroad configured — accept any key as starter (dev mode)
        return {"valid": True, "email": "", "tier": "starter", "dev_mode": True}

    result = await validate_gumroad_license(license_key)
    if result["valid"]:
        # Cache the validated license
        conn = get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            db_execute(conn,
                "INSERT INTO licenses (license_key, email, product_id, tier, active, validated_at, created_at) VALUES (?, ?, ?, ?, 1, ?, ?) ON CONFLICT(license_key) DO UPDATE SET active = 1, tier = ?, validated_at = ?",
                (license_key, result["email"], GUMROAD_PRODUCT_ID, result["tier"], now, now, result["tier"], now),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"License caching failed: {e}")
        finally:
            conn.close()

    return result


def check_tier_limit(tier: str, limit_type: str, current_count: int) -> bool:
    """Check if user is within their tier limits."""
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    max_val = limits.get(limit_type, 0)
    return current_count < max_val


# ─── DAEMON PERSISTENCE ──────────────────────────────────

def save_daemon_config(daemon_id: str, user_api_key: str, preset_id: str, agent_type: str, agent_name: str,
                        task_description: str, interval_seconds: int, max_cycles: int, alert_conditions: list):
    """Save daemon config to DB for restart persistence."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db_execute(conn,
            f"INSERT INTO daemon_configs (id, {USER_KEY_COL}, preset_id, agent_type, agent_name, task_description, interval_seconds, max_cycles, alert_conditions, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (daemon_id, user_api_key, preset_id or "", agent_type, agent_name, task_description, interval_seconds, max_cycles, json.dumps(alert_conditions), now),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Daemon config save failed: {e}")
    finally:
        conn.close()


def remove_daemon_config(daemon_id: str):
    """Remove daemon config from DB."""
    conn = get_db()
    try:
        db_execute(conn, "UPDATE daemon_configs SET enabled = 0 WHERE id = ?", (daemon_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Daemon config removal failed: {e}")
    finally:
        conn.close()


async def restore_daemons():
    """Restart enabled daemons from DB after deploy."""
    if not MISSION_CONTROL:
        return
    conn = get_db()
    try:
        rows = db_fetchall(conn,
            f"SELECT id, {USER_KEY_COL}, preset_id, agent_type, agent_name, task_description, interval_seconds, max_cycles, alert_conditions FROM daemon_configs WHERE enabled = 1"
        )
    finally:
        conn.close()

    if not rows:
        return

    logger.info(f"🔄 Restoring {len(rows)} daemon(s) from database...")
    for row in rows:
        did, user_key, preset_id, agent_type, agent_name, task_desc, interval, max_cyc, alert_json = row
        try:
            alerts = json.loads(alert_json) if alert_json else []
        except Exception:
            alerts = []
        try:
            await daemon_manager.start_daemon(
                agent_type=agent_type,
                agent_name=agent_name,
                task_description=task_desc,
                execute_fn=_daemon_execute_fn,
                interval_seconds=interval,
                max_cycles=max_cyc,
                alert_conditions=alerts,
                user_api_key=user_key,
            )
            logger.info(f"  ✅ Restored daemon: {agent_name} ({did[:8]})")
        except Exception as e:
            logger.error(f"  ❌ Failed to restore daemon {did[:8]}: {e}")


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

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


def get_api_key(x_api_key: str = Header(None), authorization: str = Header(None)) -> str:
    """Extract API key from headers."""
    key = x_api_key or ""
    if not key and authorization:
        key = authorization.replace("Bearer ", "")
    if not key:
        raise HTTPException(status_code=401, detail="API key required. Pass X-Api-Key header.")
    return key


async def get_validated_user(x_api_key: str = Header(None), authorization: str = Header(None)) -> dict:
    """Validate API key and return user info with tier."""
    key = x_api_key or ""
    if not key and authorization:
        key = authorization.replace("Bearer ", "")
    if not key:
        raise HTTPException(status_code=401, detail="API key required.")

    # Admin bypass
    if ADMIN_API_KEY and key == ADMIN_API_KEY:
        return {"api_key": key, "tier": "admin", "email": "admin"}

    # Validate license
    result = await get_or_validate_license(key)
    if not result.get("valid"):
        raise HTTPException(status_code=403, detail=result.get("error", "Invalid license key"))

    return {"api_key": key, "tier": result.get("tier", "starter"), "email": result.get("email", "")}


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

    # Emit started event
    if MISSION_CONTROL:
        await event_bus.emit(Event(
            event_type=EventType.AGENT_STARTED,
            agent_id=agent_id,
            agent_type=agent_type,
            agent_name=agent["name"],
            message=task_description[:200],
        ))

    # Inject knowledge
    knowledge = get_knowledge_for_agent(user_api_key, agent_type, task_description)
    if knowledge:
        system_prompt += knowledge

    # Inject swarm memory (shared knowledge from other agents)
    if SWARM_MEMORY and swarm_memory:
        try:
            memories = await swarm_memory.query(task_description, user_api_key=user_api_key, limit=3)
            memory_context = swarm_memory.format_for_prompt(memories)
            if memory_context:
                system_prompt += memory_context
        except Exception as e:
            logger.error(f"Swarm memory query failed: {e}")

    # Inject MCP tool context
    if MCP_AVAILABLE and mcp_registry:
        try:
            user_tools = await mcp_registry.get_tools(user_api_key, category=category)
            tool_context = mcp_registry.get_tool_definitions_for_claude(user_tools)
            if tool_context:
                system_prompt += tool_context
        except Exception as e:
            logger.error(f"MCP tool context failed: {e}")

    try:
        # Get user's MCP tools for this execution
        user_mcp_tools = None
        if MCP_AVAILABLE and mcp_registry:
            try:
                user_mcp_tools = await mcp_registry.get_tools(user_api_key)
            except Exception:
                pass

        if TOOLS_AVAILABLE:
            tools = get_tools_for_agent(category)
            result = await execute_with_tools(
                api_key=ANTHROPIC_API_KEY,
                model=CLAUDE_MODEL,
                system_prompt=system_prompt,
                user_message=task_description,
                tools=tools,
                max_turns=5,
                user_api_key=user_api_key,
                mcp_tools=user_mcp_tools,
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

        # Emit completed event
        if MISSION_CONTROL:
            await event_bus.emit(Event(
                event_type=EventType.AGENT_COMPLETED,
                agent_id=agent_id,
                agent_type=agent_type,
                agent_name=agent["name"],
                message="Task completed",
                data={"result_preview": result[:300] if result else ""},
            ))

        # Store result in swarm memory
        if SWARM_MEMORY and swarm_memory and result:
            try:
                await swarm_memory.auto_extract_and_store(
                    result=result,
                    agent_type=agent_type,
                    agent_name=agent["name"],
                    task_description=task_description,
                    user_api_key=user_api_key,
                )
            except Exception as e:
                logger.error(f"Swarm memory store failed: {e}")

        # Trigger workflows on agent completion
        if WORKFLOWS_AVAILABLE and workflow_engine:
            try:
                await workflow_engine.process_event("agent.completed", {
                    "agent_type": agent_type, "agent_name": agent["name"],
                    "message": result[:500] if result else "",
                }, user_api_key)
            except Exception as e:
                logger.error(f"Workflow trigger failed: {e}")

        return result

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

        # Emit failed event
        if MISSION_CONTROL:
            await event_bus.emit(Event(
                event_type=EventType.AGENT_FAILED,
                agent_id=agent_id,
                agent_type=agent_type,
                agent_name=agent.get("name", agent_type),
                message=str(e)[:300],
            ))

        # Trigger workflows on agent failure
        if WORKFLOWS_AVAILABLE and workflow_engine:
            try:
                await workflow_engine.process_event("agent.failed", {
                    "agent_type": agent_type, "agent_name": agent.get("name", agent_type),
                    "message": str(e)[:300],
                }, user_api_key)
            except Exception:
                pass


# Wrapper for chains module (it expects execute_fn(agent_id, agent_type, prompt))
async def _chain_execute_fn(agent_id: str, agent_type: str, prompt: str):
    await execute_task(agent_id, agent_type, prompt, user_api_key="chain")


async def _daemon_execute_fn(agent_id: str, agent_type: str, prompt: str, user_api_key: str = "daemon"):
    """Execute function for daemon agents — returns the result text."""
    return await execute_task(agent_id, agent_type, prompt, user_api_key)


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
    """Process incoming Telegram message with mission control commands."""
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

    # ─── MISSION CONTROL COMMANDS ─────
    if agent_type == "start":
        welcome = (
            "🤖 *APEX SWARM v3.1 — Mission Control*\n\n"
            "*Agent Commands:*\n"
            "/research Your question\n"
            "/crypto-research Analyze ETH\n"
            "/blog-writer Write about AI\n\n"
            "*Mission Control:*\n"
            "/god\\_eye — Live status overview\n"
            "/daemons — List running daemons\n"
            "/start\\_daemon <preset> — Start a daemon\n"
            "/stop\\_daemon <id> — Stop a daemon\n"
            "/subscribe — Get live agent feed\n"
            "/unsubscribe — Stop live feed\n"
            "/events — Recent activity log\n\n"
            "*Daemon Presets:*\n"
            "crypto-monitor, defi-yield-scanner,\n"
            "news-sentinel, whale-watcher, competitor-tracker"
        )
        await send_telegram(chat_id, welcome)
        return

    if agent_type == "god-eye" or agent_type == "god_eye":
        if not MISSION_CONTROL:
            await send_telegram(chat_id, "⚠️ Mission Control not loaded")
            return
        stats = event_bus.get_stats()
        msg = (
            "👁️ *GOD EYE — Live Status*\n\n"
            f"🤖 Active agents: *{stats['active_agents']}*\n"
            f"👁️ Active daemons: *{stats['active_daemons']}*\n"
            f"📡 SSE subscribers: *{stats['sse_subscribers']}*\n"
            f"📊 Total events: *{stats['total_events']}*\n"
            f"💬 Telegram feeds: *{stats['telegram_chats']}*\n"
        )
        if stats["active_agents_detail"]:
            msg += "\n*Running Agents:*\n"
            for aid, info in stats["active_agents_detail"].items():
                msg += f"  ⚡ {info['name']} (`{aid[:8]}`)\n"
        if stats["active_daemons_detail"]:
            msg += "\n*Running Daemons:*\n"
            for did, info in stats["active_daemons_detail"].items():
                msg += f"  👁️ {info['name']} — {info['cycles']} cycles (`{did[:8]}`)\n"
        await send_telegram(chat_id, msg)
        return

    if agent_type == "daemons":
        if not MISSION_CONTROL:
            await send_telegram(chat_id, "⚠️ Mission Control not loaded")
            return
        daemons = daemon_manager.get_daemons()
        if not daemons:
            await send_telegram(chat_id, "No active daemons. Start one with:\n/start\\_daemon crypto-monitor")
            return
        msg = "👁️ *Active Daemons:*\n\n"
        for d in daemons:
            status_icon = "🟢" if d["status"] == "running" else "🔴"
            msg += (
                f"{status_icon} *{d['agent_name']}*\n"
                f"  ID: `{d['daemon_id'][:8]}`\n"
                f"  Cycles: {d['cycles']} | Every {d['interval_seconds']}s\n"
                f"  Status: {d['status']}\n\n"
            )
        await send_telegram(chat_id, msg)
        return

    if agent_type == "start-daemon" or agent_type == "start_daemon":
        if not MISSION_CONTROL:
            await send_telegram(chat_id, "⚠️ Mission Control not loaded")
            return
        preset_id = task.strip().lower() if task else ""
        if preset_id not in DAEMON_PRESETS:
            presets = ", ".join(DAEMON_PRESETS.keys())
            await send_telegram(chat_id, f"Unknown preset. Available:\n`{presets}`")
            return
        preset = DAEMON_PRESETS[preset_id]
        daemon_id = await daemon_manager.start_daemon(
            agent_type=preset["agent_type"],
            agent_name=preset["name"],
            task_description=preset["task_description"],
            execute_fn=_daemon_execute_fn,
            interval_seconds=preset["interval_seconds"],
            alert_conditions=preset.get("alert_conditions", []),
            user_api_key=f"telegram:{chat_id}",
        )
        await send_telegram(chat_id, f"👁️ *{preset['name']}* started\nID: `{daemon_id[:8]}`\nInterval: every {preset['interval_seconds']}s\n\nStop with: /stop\\_daemon {daemon_id[:8]}")
        return

    if agent_type == "stop-daemon" or agent_type == "stop_daemon":
        if not MISSION_CONTROL:
            await send_telegram(chat_id, "⚠️ Mission Control not loaded")
            return
        short_id = task.strip()
        # Find daemon matching the short ID
        found = None
        for d in daemon_manager.get_daemons():
            if d["daemon_id"].startswith(short_id):
                found = d["daemon_id"]
                break
        if not found:
            await send_telegram(chat_id, f"No daemon found matching `{short_id}`")
            return
        await daemon_manager.stop_daemon(found)
        await send_telegram(chat_id, f"⏹️ Daemon `{short_id}` stopped")
        return

    if agent_type == "subscribe":
        if MISSION_CONTROL:
            event_bus.add_telegram_chat(chat_id)
            await send_telegram(chat_id, "📡 *Subscribed to live feed*\nYou'll receive real-time agent activity.\n\nUnsubscribe: /unsubscribe")
        return

    if agent_type == "unsubscribe":
        if MISSION_CONTROL:
            event_bus.remove_telegram_chat(chat_id)
            await send_telegram(chat_id, "🔇 Unsubscribed from live feed")
        return

    if agent_type == "events":
        if not MISSION_CONTROL:
            await send_telegram(chat_id, "⚠️ Mission Control not loaded")
            return
        events = event_bus.get_history(limit=10)
        if not events:
            await send_telegram(chat_id, "No recent events.")
            return
        msg = "📋 *Recent Events:*\n\n"
        for e in events[-10:]:
            msg += f"• `{e['event_type']}` — {e['agent_name'] or e['agent_type']}: {e['message'][:80]}\n"
        await send_telegram(chat_id, msg)
        return

    # ─── REGULAR AGENT EXECUTION ─────
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

    # Wire event bus to Telegram
    if MISSION_CONTROL and TELEGRAM_ENABLED:
        event_bus.set_telegram(send_fn=send_telegram, verbosity="important")
        logger.info("📡 Event bus → Telegram forwarding active")

    # Restore persistent daemons
    await restore_daemons()

    # Register workflow action handlers
    if WORKFLOWS_AVAILABLE and workflow_engine:
        async def _wf_deploy_agent(action, event_data, user_api_key):
            agent_type = action.get("agent_type", "research")
            # Support {variable} substitution from event data
            for key, val in event_data.items():
                if isinstance(val, str):
                    agent_type = agent_type.replace(f"{{{key}}}", val)
            task = action.get("task", "Analyze this: {message}")
            for key, val in event_data.items():
                if isinstance(val, str):
                    task = task.replace(f"{{{key}}}", val)
            if agent_type not in AGENTS:
                agent_type = "research"
            agent_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db()
            try:
                db_execute(conn,
                    f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
                    (agent_id, user_api_key, agent_type, task, now))
                conn.commit()
            finally:
                conn.close()
            asyncio.create_task(execute_task(agent_id, agent_type, task, user_api_key))
            return f"Deployed {agent_type} ({agent_id[:8]})"

        async def _wf_send_telegram(action, event_data, user_api_key):
            msg = action.get("message", "Workflow triggered")
            for key, val in event_data.items():
                if isinstance(val, str):
                    msg = msg.replace(f"{{{key}}}", val)
            # Send to all subscribed Telegram chats
            if MISSION_CONTROL and event_bus._telegram_chat_ids:
                for chat_id in event_bus._telegram_chat_ids:
                    await send_telegram(chat_id, f"⚡ *Workflow*: {msg}")
            return "Telegram sent"

        async def _wf_call_mcp(action, event_data, user_api_key):
            if not MCP_AVAILABLE or not mcp_registry:
                return "MCP not available"
            tool_id = action.get("tool_id", "")
            input_data = action.get("input_data", {})
            result = await mcp_registry.execute_tool(tool_id, user_api_key, input_data)
            return str(result)[:300]

        workflow_engine.register_action(ActionType.DEPLOY_AGENT, _wf_deploy_agent)
        workflow_engine.register_action(ActionType.SEND_TELEGRAM, _wf_send_telegram)
        workflow_engine.register_action(ActionType.CALL_MCP_TOOL, _wf_call_mcp)
        logger.info("⚡ Workflow action handlers registered")

        # Wire event bus → workflow engine
        if MISSION_CONTROL:
            async def _event_to_workflow(event):
                """Route event bus events to workflow engine."""
                event_data = {
                    "agent_type": event.agent_type,
                    "agent_name": event.agent_name,
                    "message": event.message,
                    "data": event.data,
                }
                # Process for all users (user_api_key=None means check all)
                await workflow_engine.process_event(event.event_type, event_data)
            event_bus.add_post_emit_hook(_event_to_workflow)
            logger.info("📡 Event bus → Workflow engine connected")

    db_type = "PostgreSQL" if USE_POSTGRES else "SQLite"
    logger.info(f"🚀 APEX SWARM v{VERSION} starting ({db_type})")
    logger.info(f"   Tools: {'✅' if TOOLS_AVAILABLE else '❌'} | Chains: {'✅' if CHAINS_AVAILABLE else '❌'} | Knowledge: {'✅' if SMART_KNOWLEDGE else '❌'} | Mission Control: {'✅' if MISSION_CONTROL else '❌'}")
    logger.info(f"   Memory: {'✅' if SWARM_MEMORY else '❌'} | MCP: {'✅' if MCP_AVAILABLE else '❌'} | Workflows: {'✅' if WORKFLOWS_AVAILABLE else '❌'} | Rate Limit: {'✅' if rate_limiter else '❌'}")
    logger.info(f"   Auth: {'Gumroad' if GUMROAD_PRODUCT_ID else 'Dev mode (any key)'} | DB: {db_type}")
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
        "mission_control": MISSION_CONTROL,
        "telegram": TELEGRAM_ENABLED,
        "database": "postgresql" if USE_POSTGRES else "sqlite",
        "auth": "gumroad" if GUMROAD_PRODUCT_ID else "dev_mode",
        "swarm_memory": SWARM_MEMORY,
        "mcp_registry": MCP_AVAILABLE,
        "rate_limiting": rate_limiter is not None,
    }


# ─── LEGACY v2.1 STUBS (silence 404s from old polling) ───

@app.get("/api/v1/tasks")
async def legacy_tasks(request: Request):
    client = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    logger.info(f"👻 Legacy /tasks hit from {client} (UA: {ua[:80]})")
    return {"tasks": [], "message": "Migrated to v3.1 — use /api/v1/history", "version": VERSION}


@app.get("/api/v1/stats")
async def legacy_stats(request: Request):
    client = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    logger.info(f"👻 Legacy /stats hit from {client} (UA: {ua[:80]})")
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'completed'").fetchone()[0]
    finally:
        conn.close()
    return {"total_tasks": total, "completed": completed, "agents": len(AGENTS), "version": VERSION}


# ─── MISSION CONTROL ENDPOINTS ───────────────────────────

@app.get("/api/v1/events/stream")
async def event_stream(request: Request):
    """SSE endpoint — real-time God-eye stream of all agent activity."""
    if not MISSION_CONTROL:
        raise HTTPException(status_code=503, detail="Mission Control not loaded")

    async def generate():
        queue = event_bus.subscribe()
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {{\"message\": \"God-eye connected\", \"version\": \"{VERSION}\"}}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"event: heartbeat\ndata: {{\"ts\": \"{datetime.now(timezone.utc).isoformat()}\"}}\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/events")
async def get_events(limit: int = 50, event_type: str = None):
    """Get recent event history."""
    if not MISSION_CONTROL:
        return {"events": [], "message": "Mission Control not loaded"}
    return {"events": event_bus.get_history(limit=limit, event_type=event_type)}


@app.get("/api/v1/god-eye")
async def god_eye_status():
    """God-eye overview — current state of everything."""
    stats = event_bus.get_stats() if MISSION_CONTROL else {}
    conn = get_db()
    try:
        running = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'running'").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'completed'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM agents WHERE status = 'failed'").fetchone()[0]
    finally:
        conn.close()

    return {
        "version": VERSION,
        "mission_control": MISSION_CONTROL,
        "db": {"running": running, "total": total, "completed": completed, "failed": failed},
        "live": stats,
        "modules": {
            "tools": TOOLS_AVAILABLE,
            "chains": CHAINS_AVAILABLE,
            "knowledge": SMART_KNOWLEDGE,
            "mission_control": MISSION_CONTROL,
            "telegram": TELEGRAM_ENABLED,
        },
    }


# ─── USAGE & COST ENDPOINTS ──────────────────────────────

@app.get("/api/v1/usage")
async def get_usage(api_key: str = Depends(get_api_key), days: int = 30):
    """Get token usage and cost summary."""
    conn = get_db()
    try:
        # Total usage
        row = db_fetchone(conn,
            f"SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost_usd),0), COUNT(*) FROM usage_log WHERE {USER_KEY_COL} = ?",
            (api_key,),
        )
        total_input, total_output, total_cost, total_calls = row if row else (0, 0, 0, 0)

        # Per-agent breakdown
        rows = db_fetchall(conn,
            f"SELECT agent_type, SUM(input_tokens), SUM(output_tokens), SUM(cost_usd), COUNT(*) FROM usage_log WHERE {USER_KEY_COL} = ? GROUP BY agent_type ORDER BY SUM(cost_usd) DESC LIMIT 20",
            (api_key,),
        )
        by_agent = [
            {"agent_type": r[0], "input_tokens": r[1], "output_tokens": r[2], "cost_usd": round(r[3], 6), "calls": r[4]}
            for r in rows
        ]
    finally:
        conn.close()

    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "total_calls": total_calls,
        "by_agent": by_agent,
    }


@app.post("/api/v1/license/validate")
async def validate_license(request: Request):
    """Validate a Gumroad license key."""
    data = await request.json()
    key = data.get("license_key", "")
    if not key:
        raise HTTPException(status_code=400, detail="license_key required")

    result = await get_or_validate_license(key)
    if result.get("valid"):
        tier = result.get("tier", "starter")
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["starter"])
        return {"valid": True, "tier": tier, "email": result.get("email", ""), "limits": limits}
    else:
        return {"valid": False, "error": result.get("error", "Invalid license")}


# ─── DAEMON ENDPOINTS ────────────────────────────────────

class DaemonRequest(BaseModel):
    preset_id: Optional[str] = None
    agent_type: str = "research"
    agent_name: str = "Custom Daemon"
    task_description: str = ""
    interval_seconds: int = 300
    max_cycles: int = 0
    alert_conditions: list[str] = []


@app.post("/api/v1/daemons")
async def start_daemon(req: DaemonRequest, api_key: str = Depends(get_api_key)):
    if not MISSION_CONTROL:
        raise HTTPException(status_code=503, detail="Mission Control not loaded")

    if req.preset_id and req.preset_id in DAEMON_PRESETS:
        preset = DAEMON_PRESETS[req.preset_id]
        task_desc = req.task_description or preset["task_description"]
        daemon_id = await daemon_manager.start_daemon(
            agent_type=preset["agent_type"],
            agent_name=preset["name"],
            task_description=task_desc,
            execute_fn=_daemon_execute_fn,
            interval_seconds=preset["interval_seconds"],
            alert_conditions=preset.get("alert_conditions", []),
            user_api_key=api_key,
        )
        save_daemon_config(daemon_id, api_key, req.preset_id, preset["agent_type"], preset["name"],
                           task_desc, preset["interval_seconds"], 0, preset.get("alert_conditions", []))
        return {"daemon_id": daemon_id, "name": preset["name"], "status": "running", "persistent": True}
    elif req.task_description:
        daemon_id = await daemon_manager.start_daemon(
            agent_type=req.agent_type,
            agent_name=req.agent_name,
            task_description=req.task_description,
            execute_fn=_daemon_execute_fn,
            interval_seconds=req.interval_seconds,
            max_cycles=req.max_cycles,
            alert_conditions=req.alert_conditions,
            user_api_key=api_key,
        )
        save_daemon_config(daemon_id, api_key, "", req.agent_type, req.agent_name,
                           req.task_description, req.interval_seconds, req.max_cycles, req.alert_conditions)
        return {"daemon_id": daemon_id, "name": req.agent_name, "status": "running", "persistent": True}
    else:
        raise HTTPException(status_code=400, detail="Provide preset_id or task_description")


@app.get("/api/v1/daemons")
async def list_daemons():
    if not MISSION_CONTROL:
        return {"daemons": [], "message": "Mission Control not loaded"}
    return {"daemons": daemon_manager.get_daemons()}


@app.get("/api/v1/daemons/presets")
async def list_daemon_presets():
    return {
        "presets": {
            pid: {"name": p["name"], "description": p["description"], "agent_type": p["agent_type"], "interval": p["interval_seconds"]}
            for pid, p in DAEMON_PRESETS.items()
        }
    }


@app.delete("/api/v1/daemons/{daemon_id}")
async def stop_daemon(daemon_id: str, api_key: str = Depends(get_api_key)):
    if not MISSION_CONTROL:
        raise HTTPException(status_code=503, detail="Mission Control not loaded")
    # Support short IDs
    found = None
    for d in daemon_manager.get_daemons():
        if d["daemon_id"].startswith(daemon_id):
            found = d["daemon_id"]
            break
    if not found:
        raise HTTPException(status_code=404, detail="Daemon not found")
    await daemon_manager.stop_daemon(found)
    remove_daemon_config(found)
    return {"status": "stopped", "daemon_id": found}


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

    # Rate limit check
    if rate_limiter:
        check = rate_limiter.check(api_key, "starter")  # TODO: get tier from validated user
        if not check["allowed"]:
            raise HTTPException(status_code=429, detail=check["message"])
        rate_limiter.consume(api_key, "starter")

    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        db_execute(conn,
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


# ─── MCP TOOL ENDPOINTS ──────────────────────────────────

class MCPToolRequest(BaseModel):
    name: str
    description: str
    endpoint_url: str
    method: str = "GET"
    headers: dict = {}
    body_template: str = ""
    query_params: dict = {}
    auth_type: str = "none"
    auth_value: str = ""
    input_schema: dict = {}
    category: str = "general"


@app.post("/api/v1/mcp/tools")
async def register_mcp_tool(req: MCPToolRequest, api_key: str = Depends(get_api_key)):
    if not MCP_AVAILABLE or not mcp_registry:
        raise HTTPException(status_code=503, detail="MCP registry not loaded")
    result = await mcp_registry.register_tool(
        user_api_key=api_key, name=req.name, description=req.description,
        endpoint_url=req.endpoint_url, method=req.method, headers=req.headers,
        body_template=req.body_template, query_params=req.query_params,
        auth_type=req.auth_type, auth_value=req.auth_value,
        input_schema=req.input_schema, category=req.category,
    )
    return result


@app.get("/api/v1/mcp/tools")
async def list_mcp_tools(api_key: str = Depends(get_api_key), category: str = None):
    if not MCP_AVAILABLE or not mcp_registry:
        return {"tools": []}
    tools = await mcp_registry.get_tools(api_key, category=category)
    return {"tools": tools}


@app.post("/api/v1/mcp/tools/{tool_id}/execute")
async def execute_mcp_tool(tool_id: str, request: Request, api_key: str = Depends(get_api_key)):
    if not MCP_AVAILABLE or not mcp_registry:
        raise HTTPException(status_code=503, detail="MCP registry not loaded")
    data = await request.json()
    result = await mcp_registry.execute_tool(tool_id, api_key, input_data=data)
    return result


@app.delete("/api/v1/mcp/tools/{tool_id}")
async def delete_mcp_tool(tool_id: str, api_key: str = Depends(get_api_key)):
    if not MCP_AVAILABLE or not mcp_registry:
        raise HTTPException(status_code=503, detail="MCP registry not loaded")
    await mcp_registry.delete_tool(tool_id, api_key)
    return {"status": "deleted"}


@app.get("/api/v1/mcp/templates")
async def list_mcp_templates():
    return {"templates": MCP_TEMPLATES}


# ─── SWARM MEMORY ENDPOINTS ─────────────────────────────

@app.get("/api/v1/memory")
async def query_memory(q: str = "", namespace: str = None, limit: int = 5, api_key: str = Depends(get_api_key)):
    if not SWARM_MEMORY or not swarm_memory:
        return {"memories": [], "message": "Swarm memory not loaded"}
    if not q:
        return {"memories": [], "message": "Provide ?q= query parameter"}
    memories = await swarm_memory.query(q, namespace=namespace, user_api_key=api_key, limit=limit)
    return {"memories": memories, "count": len(memories)}


@app.get("/api/v1/memory/stats")
async def memory_stats(api_key: str = Depends(get_api_key)):
    if not SWARM_MEMORY or not swarm_memory:
        return {"stats": {}, "message": "Swarm memory not loaded"}
    stats = await swarm_memory.get_stats(user_api_key=api_key)
    return {"stats": stats}


@app.post("/api/v1/memory/cleanup")
async def memory_cleanup(api_key: str = Depends(get_api_key)):
    if not SWARM_MEMORY or not swarm_memory:
        raise HTTPException(status_code=503, detail="Swarm memory not loaded")
    await swarm_memory.cleanup(user_api_key=api_key)
    return {"status": "cleanup complete"}


# ─── RATE LIMIT ENDPOINT ────────────────────────────────

@app.get("/api/v1/rate-limit")
async def check_rate_limit(api_key: str = Depends(get_api_key)):
    if not rate_limiter:
        return {"message": "Rate limiting not active"}
    return rate_limiter.get_usage(api_key, "starter")


# ─── WORKFLOW ENDPOINTS ──────────────────────────────────

class WorkflowRequest(BaseModel):
    name: str
    trigger_type: str
    actions: list[dict]
    description: str = ""
    trigger_filter: dict = {}
    conditions: list[dict] = []
    template_id: Optional[str] = None


@app.post("/api/v1/workflows")
async def create_workflow(req: WorkflowRequest, api_key: str = Depends(get_api_key)):
    if not WORKFLOWS_AVAILABLE or not workflow_engine:
        raise HTTPException(status_code=503, detail="Workflow engine not loaded")

    # If using template, override with template values
    if req.template_id and req.template_id in WORKFLOW_TEMPLATES:
        tmpl = WORKFLOW_TEMPLATES[req.template_id]
        wf_id = await workflow_engine.create_workflow(
            user_api_key=api_key,
            name=req.name or tmpl["name"],
            trigger_type=tmpl["trigger_type"],
            actions=tmpl["actions"],
            description=tmpl.get("description", ""),
            trigger_filter=tmpl.get("trigger_filter"),
            conditions=req.conditions,
        )
        return {"workflow_id": wf_id, "name": tmpl["name"], "status": "active"}

    wf_id = await workflow_engine.create_workflow(
        user_api_key=api_key,
        name=req.name,
        trigger_type=req.trigger_type,
        actions=req.actions,
        description=req.description,
        trigger_filter=req.trigger_filter,
        conditions=req.conditions,
    )
    return {"workflow_id": wf_id, "name": req.name, "status": "active"}


@app.get("/api/v1/workflows")
async def list_workflows(api_key: str = Depends(get_api_key)):
    if not WORKFLOWS_AVAILABLE or not workflow_engine:
        return {"workflows": []}
    workflows = await workflow_engine.get_workflows(api_key)
    return {"workflows": workflows}


@app.get("/api/v1/workflows/templates")
async def list_workflow_templates():
    return {"templates": WORKFLOW_TEMPLATES}


@app.delete("/api/v1/workflows/{wf_id}")
async def delete_workflow(wf_id: str, api_key: str = Depends(get_api_key)):
    if not WORKFLOWS_AVAILABLE or not workflow_engine:
        raise HTTPException(status_code=503, detail="Workflow engine not loaded")
    await workflow_engine.delete_workflow(wf_id, api_key)
    return {"status": "deleted"}


@app.post("/api/v1/workflows/{wf_id}/toggle")
async def toggle_workflow(wf_id: str, api_key: str = Depends(get_api_key)):
    if not WORKFLOWS_AVAILABLE or not workflow_engine:
        raise HTTPException(status_code=503, detail="Workflow engine not loaded")
    await workflow_engine.toggle_workflow(wf_id, api_key)
    return {"status": "toggled"}


@app.get("/api/v1/workflows/{wf_id}/logs")
async def workflow_logs(wf_id: str, api_key: str = Depends(get_api_key)):
    if not WORKFLOWS_AVAILABLE or not workflow_engine:
        return {"logs": []}
    logs = await workflow_engine.get_workflow_logs(wf_id, api_key)
    return {"logs": logs}


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
  <div class="tab" data-tab="godeye">👁️ God Eye</div>
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

  <!-- GOD EYE TAB -->
  <div class="tab-content" id="tab-godeye">
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:24px;" id="godeyeStats">
      <div class="card" style="text-align:center;cursor:default;">
        <div style="font-size:32px;font-family:'Fraunces',serif;color:var(--accent);" id="geActiveAgents">0</div>
        <div style="color:var(--text2);font-size:13px;">Active Agents</div>
      </div>
      <div class="card" style="text-align:center;cursor:default;">
        <div style="font-size:32px;font-family:'Fraunces',serif;color:var(--success);" id="geActiveDaemons">0</div>
        <div style="color:var(--text2);font-size:13px;">Daemons Running</div>
      </div>
      <div class="card" style="text-align:center;cursor:default;">
        <div style="font-size:32px;font-family:'Fraunces',serif;color:var(--warning);" id="geTotalEvents">0</div>
        <div style="color:var(--text2);font-size:13px;">Total Events</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <!-- Daemons Panel -->
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <h3 style="font-family:'Fraunces',serif;">Daemons</h3>
          <select id="daemonPreset" style="padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px;">
            <option value="">Start daemon...</option>
          </select>
          <button class="btn btn-primary btn-sm" onclick="startDaemon()">Start</button>
        </div>
        <div id="daemonList"></div>
      </div>

      <!-- Live Event Feed -->
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <h3 style="font-family:'Fraunces',serif;">Live Feed</h3>
          <div>
            <button class="btn btn-sm" id="sseToggle" onclick="toggleSSE()" style="background:var(--success);color:white;">● Connected</button>
          </div>
        </div>
        <div id="eventFeed" style="max-height:500px;overflow-y:auto;display:flex;flex-direction:column-reverse;gap:6px;"></div>
      </div>
    </div>
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
    if (tab.dataset.tab === 'godeye') { loadDaemons(); refreshGodEye(); connectSSE(); }
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

// ─── God Eye ───
let sseSource = null;
let sseConnected = false;

function toggleSSE() {
  if (sseConnected) { disconnectSSE(); } else { connectSSE(); }
}

function connectSSE() {
  if (sseSource) sseSource.close();
  sseSource = new EventSource(API + '/api/v1/events/stream');
  sseSource.onopen = () => {
    sseConnected = true;
    const btn = document.getElementById('sseToggle');
    if (btn) { btn.style.background = 'var(--success)'; btn.textContent = '● Connected'; }
  };
  sseSource.onerror = () => {
    sseConnected = false;
    const btn = document.getElementById('sseToggle');
    if (btn) { btn.style.background = 'var(--danger)'; btn.textContent = '○ Disconnected'; }
  };
  sseSource.addEventListener('agent.started', (e) => addFeedEvent(JSON.parse(e.data), '🚀'));
  sseSource.addEventListener('agent.completed', (e) => addFeedEvent(JSON.parse(e.data), '✅'));
  sseSource.addEventListener('agent.failed', (e) => addFeedEvent(JSON.parse(e.data), '❌'));
  sseSource.addEventListener('tool.called', (e) => addFeedEvent(JSON.parse(e.data), '🔧'));
  sseSource.addEventListener('daemon.started', (e) => addFeedEvent(JSON.parse(e.data), '👁️'));
  sseSource.addEventListener('daemon.cycle', (e) => addFeedEvent(JSON.parse(e.data), '🔄'));
  sseSource.addEventListener('daemon.alert', (e) => addFeedEvent(JSON.parse(e.data), '🚨'));
  sseSource.addEventListener('daemon.stopped', (e) => addFeedEvent(JSON.parse(e.data), '⏹️'));
  sseSource.addEventListener('chain.started', (e) => addFeedEvent(JSON.parse(e.data), '🔗'));
  sseSource.addEventListener('chain.completed', (e) => addFeedEvent(JSON.parse(e.data), '🏁'));
  sseSource.addEventListener('schedule.fired', (e) => addFeedEvent(JSON.parse(e.data), '⏰'));
  sseSource.addEventListener('connected', () => addFeedEvent({message:'God-eye connected',timestamp:new Date().toISOString()}, '📡'));
}

function disconnectSSE() {
  if (sseSource) sseSource.close();
  sseConnected = false;
  const btn = document.getElementById('sseToggle');
  if (btn) { btn.style.background = 'var(--border)'; btn.textContent = '○ Disconnected'; }
}

function addFeedEvent(data, icon) {
  const feed = document.getElementById('eventFeed');
  if (!feed) return;
  const time = data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : '';
  const name = data.agent_name || data.agent_type || '';
  const msg = data.message || data.event_type || '';
  const el = document.createElement('div');
  el.style.cssText = 'padding:8px 12px;background:var(--surface);border:1px solid var(--border);border-radius:8px;font-size:12px;';
  el.innerHTML = '<span style="opacity:0.5">' + time + '</span> ' + icon + ' <strong>' + name + '</strong> ' + msg.substring(0,120);
  // If alert, highlight
  if (data.event_type === 'daemon.alert') el.style.borderColor = 'var(--danger)';
  feed.prepend(el);
  // Keep feed manageable
  while (feed.children.length > 100) feed.removeChild(feed.lastChild);
  // Update stats
  refreshGodEye();
}

async function refreshGodEye() {
  try {
    const r = await fetch(API + '/api/v1/god-eye');
    const d = await r.json();
    const ge = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    ge('geActiveAgents', (d.live?.active_agents || d.db?.running || 0));
    ge('geActiveDaemons', d.live?.active_daemons || 0);
    ge('geTotalEvents', d.live?.total_events || 0);
  } catch(e) {}
}

async function loadDaemons() {
  try {
    // Load presets into dropdown
    const pr = await fetch(API + '/api/v1/daemons/presets');
    const presets = await pr.json();
    const sel = document.getElementById('daemonPreset');
    if (sel && presets.presets) {
      sel.innerHTML = '<option value="">Select preset...</option>';
      for (const [id, p] of Object.entries(presets.presets)) {
        sel.innerHTML += '<option value="' + id + '">' + p.name + ' (' + p.interval + 's)</option>';
      }
    }

    // Load active daemons
    const dr = await fetch(API + '/api/v1/daemons', { headers: headers() });
    const data = await dr.json();
    const list = document.getElementById('daemonList');
    if (!list) return;
    if (!data.daemons || data.daemons.length === 0) {
      list.innerHTML = '<div class="empty-state" style="padding:30px"><div class="icon">👁️</div><p>No daemons running</p></div>';
      return;
    }
    let html = '';
    for (const d of data.daemons) {
      const statusColor = d.status === 'running' ? 'var(--success)' : 'var(--danger)';
      html += '<div class="schedule-row">' +
        '<div class="schedule-info">' +
          '<div class="sched-agent" style="color:' + statusColor + '">' + (d.status === 'running' ? '🟢' : '🔴') + ' ' + d.agent_name + '</div>' +
          '<div class="sched-task">' + (d.task || '').substring(0,80) + '</div>' +
          '<div class="sched-cron">Cycles: ' + d.cycles + ' | Every ' + d.interval_seconds + 's | ID: ' + d.daemon_id.substring(0,8) + '</div>' +
        '</div>' +
        '<div class="schedule-actions">' +
          (d.status === 'running' ? '<button class="btn btn-danger btn-sm" onclick="stopDaemon(\'' + d.daemon_id + '\')">Stop</button>' : '') +
        '</div>' +
      '</div>';
    }
    list.innerHTML = html;
  } catch(e) { console.error(e); }
}

async function startDaemon() {
  const presetId = document.getElementById('daemonPreset').value;
  if (!presetId) return alert('Select a daemon preset');
  try {
    await fetch(API + '/api/v1/daemons', {
      method: 'POST', headers: headers(),
      body: JSON.stringify({ preset_id: presetId })
    });
    loadDaemons();
  } catch(e) { alert('Failed: ' + e.message); }
}

async function stopDaemon(id) {
  if (!confirm('Stop this daemon?')) return;
  await fetch(API + '/api/v1/daemons/' + id, { method: 'DELETE', headers: headers() });
  loadDaemons();
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
