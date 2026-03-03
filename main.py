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
VERSION = "4.0.0"

# ─── OPTIONAL MODULE IMPORTS (graceful degradation) ───────

TOOLS_AVAILABLE = False
CHAINS_AVAILABLE = False
MISSION_CONTROL = False

try:
    from agent_tools import execute_with_tools, get_tools_for_agent, set_mcp_registry, get_mcp_tool_definitions, set_model_router
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

# Multi-model router
MULTI_MODEL = False
model_router = None
try:
    from multi_model import ModelRouter, PROVIDERS, model_router as _mr
    MULTI_MODEL = True
    model_router = _mr
    logger.info("✅ multi_model loaded — 9 providers, 30+ models available")
except ImportError:
    PROVIDERS = {}
    logger.warning("⚠️ multi_model not found — Anthropic-only mode")

# Unified channels (Telegram + Discord + Slack)
CHANNELS_LOADED = False
try:
    from channels import (
        command_router, discord_gateway, send_telegram, send_discord, send_slack,
        send_to_channel, parse_telegram_webhook, parse_discord_webhook, parse_slack_webhook,
        setup_telegram_webhook, get_channel_status,
        TELEGRAM_ENABLED, DISCORD_ENABLED, SLACK_ENABLED,
    )
    CHANNELS_LOADED = True
    logger.info("✅ channels loaded — Telegram/Discord/Slack")
except ImportError:
    TELEGRAM_ENABLED = bool(os.getenv("TELEGRAM_BOT_TOKEN", ""))
    DISCORD_ENABLED = False
    SLACK_ENABLED = False
    logger.warning("⚠️ channels not found — limited messaging")

# Agent Marketplace
MARKETPLACE_AVAILABLE = False
marketplace = None
try:
    from marketplace import Marketplace, STARTER_AGENTS
    MARKETPLACE_AVAILABLE = True
    logger.info("✅ marketplace loaded — agent store, revenue sharing, skill packs")
except ImportError:
    STARTER_AGENTS = []
    logger.warning("⚠️ marketplace not found — no agent store")

# Voice pipeline (STT + TTS)
VOICE_AVAILABLE = False
voice_pipeline = None
try:
    from voice import voice_pipeline as _vp, VoicePipeline, download_telegram_voice, VOICE_OPTIONS
    VOICE_AVAILABLE = True
    voice_pipeline = _vp
    logger.info("✅ voice loaded — speech-to-text + text-to-speech")
except ImportError:
    VOICE_OPTIONS = {}
    logger.warning("⚠️ voice not found — no voice interface")

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
            "automation-builder": {"name": "Automation Builder", "description": "Design no-code/low-code automations and agent workflows", "system": "You are an automation architect. Design workflows connecting APIs, tools, and AI agents using platforms like Make, Zapier, n8n, or custom pipelines. Map triggers, conditions, and actions."},
            "workflow-optimizer": {"name": "Workflow Optimizer", "description": "Analyze and optimize business processes with AI agents", "system": "You are a workflow optimization specialist focused on AI agent integration. Audit existing business processes, identify bottlenecks, and design agent-augmented workflows that reduce manual work by 10x."},
            "prompt-engineer": {"name": "Prompt Engineer", "description": "Craft and optimize prompts and system instructions for AI agents", "system": "You are an expert prompt engineer. Design, test, and optimize system prompts, tool definitions, and instruction sets for AI agents and LLMs."},
        },
    },
    "DevOps & Monitoring": {
        "icon": "🔧",
        "agents": {
            "uptime-monitor": {"name": "Uptime Monitor", "description": "Monitor endpoints and APIs for uptime and response time", "system": "You are an uptime monitoring specialist. Check HTTP endpoints, measure response times, detect outages, and generate status reports. Use json_api and web_search tools to verify service health. Recommend fixes for common failure patterns."},
            "log-analyzer": {"name": "Log Analyzer", "description": "Analyze application logs for errors, patterns, and anomalies", "system": "You are a log analysis expert. Parse application logs, identify error patterns, detect anomalies, correlate events, and provide root cause analysis. Prioritize by severity and frequency."},
            "dependency-scanner": {"name": "Dependency Scanner", "description": "Scan project dependencies for vulnerabilities and updates", "system": "You are a dependency security expert. Check package registries for known CVEs, outdated versions, and license risks. Recommend upgrade paths and security patches."},
            "infra-cost-analyzer": {"name": "Infrastructure Cost Analyst", "description": "Analyze and optimize cloud infrastructure costs", "system": "You are a cloud cost optimization expert. Analyze cloud spending across AWS, GCP, Azure. Identify idle resources, right-sizing opportunities, reserved instance savings, and architectural changes that reduce costs."},
            "api-tester": {"name": "API Tester", "description": "Test API endpoints for correctness, performance, and edge cases", "system": "You are an API testing specialist. Use json_api tool to test endpoints. Verify response codes, data formats, error handling, auth flows, and edge cases. Generate test reports with pass/fail status."},
            "release-manager": {"name": "Release Manager", "description": "Coordinate releases, changelogs, and deployment plans", "system": "You are a release management expert. Create structured release plans, generate changelogs from commit history, coordinate deployment steps, rollback procedures, and stakeholder communications."},
        },
    },
    "Intelligence & OSINT": {
        "icon": "🕵️",
        "agents": {
            "social-listener": {"name": "Social Listener", "description": "Monitor social media for brand mentions, sentiment, and trends", "system": "You are a social media intelligence analyst. Monitor Twitter/X, Reddit, HackerNews, and forums for brand mentions, sentiment shifts, and viral trends. Use web_search and rss_feed tools. Analyze sentiment with sentiment_analysis tool. Track competitor mentions and industry discourse."},
            "patent-researcher": {"name": "Patent Researcher", "description": "Research patent filings and intellectual property landscape", "system": "You are a patent intelligence analyst. Research patent filings on Google Patents and USPTO. Identify IP trends, potential infringement risks, and white space opportunities in any technology domain."},
            "regulatory-tracker": {"name": "Regulatory Tracker", "description": "Track regulatory changes and compliance updates", "system": "You are a regulatory intelligence specialist. Monitor government sites, Federal Register, SEC filings, and regulatory bodies for policy changes, new rules, and compliance requirements that affect businesses."},
            "talent-scout": {"name": "Talent Scout", "description": "Research talent pools, hiring trends, and team building", "system": "You are a talent intelligence analyst. Research hiring trends, salary benchmarks, skill availability, and competitive talent landscapes using job boards, LinkedIn data, and industry reports."},
            "supply-chain-analyst": {"name": "Supply Chain Analyst", "description": "Monitor supply chain risks and logistics intelligence", "system": "You are a supply chain intelligence analyst. Monitor shipping data, commodity prices, geopolitical risks, weather disruptions, and supplier health that could impact supply chains."},
            "dark-web-monitor": {"name": "Threat Intel Monitor", "description": "Monitor for data breaches, leaked credentials, and threat intelligence", "system": "You are a cybersecurity threat intelligence analyst. Monitor security feeds, CVE databases, breach notification sites, and security advisories for threats relevant to an organization. Use web_search and rss_feed tools."},
        },
    },
    "Sales & Growth": {
        "icon": "📈",
        "agents": {
            "lead-qualifier": {"name": "Lead Qualifier", "description": "Research and qualify sales leads from company data", "system": "You are a B2B lead qualification expert. Research companies using web_search, analyze their tech stack, funding, team size, and growth signals. Score leads on ICP fit, buying intent, and timing."},
            "pitch-writer": {"name": "Pitch Writer", "description": "Write compelling sales pitches and proposals", "system": "You are an expert sales copywriter. Craft personalized pitches, proposals, and outreach sequences tailored to the prospect's pain points, industry, and decision stage."},
            "pricing-optimizer": {"name": "Pricing Optimizer", "description": "Analyze pricing strategies and competitive positioning", "system": "You are a pricing strategy expert. Analyze competitive pricing, willingness-to-pay signals, packaging structures, and recommend optimal pricing strategies. Use data_transform for analysis."},
            "churn-predictor": {"name": "Churn Predictor", "description": "Analyze customer signals to predict and prevent churn", "system": "You are a customer retention analyst. Analyze usage patterns, support tickets, NPS signals, and engagement metrics to identify churn risks and recommend retention interventions."},
            "market-sizer": {"name": "Market Sizer", "description": "Estimate TAM/SAM/SOM for market opportunities", "system": "You are a market sizing expert. Estimate Total Addressable Market, Serviceable Addressable Market, and Serviceable Obtainable Market using top-down and bottom-up methodologies with current industry data."},
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

    # Wire multi-model router into agent_tools
    if MULTI_MODEL and TOOLS_AVAILABLE and model_router:
        set_model_router(model_router)
        logger.info("✅ Multi-model router wired into agent execution")

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

    # Initialize marketplace tables
    if MARKETPLACE_AVAILABLE:
        global marketplace
        marketplace = Marketplace(get_db, db_execute, db_fetchall, db_fetchone, USER_KEY_COL)
        conn = get_db()
        try:
            marketplace.init_tables(conn)
            logger.info("✅ Marketplace tables initialized")
        except Exception as e:
            logger.error(f"Marketplace init failed: {e}")
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
    model: Optional[str] = None  # e.g. "gpt-4o", "gemini-2.5-flash", "groq/llama-3.3-70b-versatile"
    image_url: Optional[str] = None  # URL of image for vision tasks

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

async def execute_task(agent_id: str, agent_type: str, task_description: str, user_api_key: str = "system", model: str = None, image_data: str = None, image_media_type: str = "image/jpeg"):
    """Execute a single agent task. Supports built-in + marketplace agents."""
    marketplace_agent = None

    # Check if it's a marketplace agent (format: mp:slug or mp:agent_id)
    if agent_type.startswith("mp:") and MARKETPLACE_AVAILABLE and marketplace:
        mp_ref = agent_type[3:]
        marketplace_agent = await marketplace.get_agent_detail(mp_ref)
        if not marketplace_agent:
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE agents SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                    (f"Marketplace agent not found: {mp_ref}", datetime.now(timezone.utc).isoformat(), agent_id),
                )
                conn.commit()
            finally:
                conn.close()
            return
        # Record the run
        await marketplace.record_run(marketplace_agent["agent_id"], user_api_key)

    elif agent_type not in AGENTS:
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

    # Resolve agent config — marketplace or built-in
    if marketplace_agent:
        agent = {"name": marketplace_agent["name"], "system": marketplace_agent["system_prompt"]}
        category = marketplace_agent.get("category", "Productivity")
        system_prompt = marketplace_agent["system_prompt"]
        # Use marketplace agent's model preference if set and no override
        if not model and marketplace_agent.get("model_preference"):
            model = marketplace_agent["model_preference"]
    else:
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
            # Use requested model, or env default, or auto-select
            selected_model = model or CLAUDE_MODEL
            result = await execute_with_tools(
                api_key=ANTHROPIC_API_KEY,
                model=selected_model,
                system_prompt=system_prompt,
                user_message=task_description,
                tools=tools,
                max_turns=5,
                user_api_key=user_api_key,
                mcp_tools=user_mcp_tools,
                image_data=image_data,
                image_media_type=image_media_type,
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

    # Wire unified channels
    if CHANNELS_LOADED:
        command_router.setup(
            agents=AGENTS,
            agent_to_category=AGENT_TO_CATEGORY,
            execute_fn=execute_task,
            event_bus=event_bus if MISSION_CONTROL else None,
            daemon_manager=daemon_manager if MISSION_CONTROL else None,
            daemon_presets=DAEMON_PRESETS if MISSION_CONTROL else {},
            daemon_execute_fn=_daemon_execute_fn if MISSION_CONTROL else None,
            get_db=get_db,
            user_key_col=USER_KEY_COL,
        )
        channels_active = []
        if TELEGRAM_ENABLED: channels_active.append("Telegram")
        if DISCORD_ENABLED: channels_active.append("Discord")
        if SLACK_ENABLED: channels_active.append("Slack")
        if channels_active:
            logger.info(f"💬 Channels active: {', '.join(channels_active)}")

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
    logger.info(f"   Multi-Model: {'✅ ' + str(len([p for p in model_router.get_available_providers() if p['available']])) + ' providers' if MULTI_MODEL and model_router else '❌ Anthropic-only'}")
    channels_str = "/".join([c for c, e in [("TG", TELEGRAM_ENABLED), ("DC", DISCORD_ENABLED), ("SL", SLACK_ENABLED)] if e]) or "none"
    logger.info(f"   Channels: {channels_str} | Marketplace: {'✅' if MARKETPLACE_AVAILABLE else '❌'} | Voice: {'✅' if VOICE_AVAILABLE else '❌'} | Auth: {'Gumroad' if GUMROAD_PRODUCT_ID else 'Dev mode (any key)'} | DB: {db_type}")
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
        "multi_model": MULTI_MODEL,
        "workflows": WORKFLOWS_AVAILABLE,
        "channels": {"telegram": TELEGRAM_ENABLED, "discord": DISCORD_ENABLED, "slack": SLACK_ENABLED},
        "marketplace": MARKETPLACE_AVAILABLE,
        "voice": VOICE_AVAILABLE,
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
    """List all available agent types grouped by category + flat list."""
    result = {}
    flat = []
    for cat_name, cat_data in AGENT_CATEGORIES.items():
        result[cat_name] = {
            "icon": cat_data["icon"],
            "agents": {
                aid: {"name": a["name"], "description": a["description"]}
                for aid, a in cat_data["agents"].items()
            },
        }
        for aid, a in cat_data["agents"].items():
            flat.append({"type": aid, "name": a["name"], "description": a["description"], "category": cat_name})
    return {"categories": result, "agents": flat, "total": len(flat)}


@app.get("/api/v1/agents/recent")
async def recent_agents(limit: int = 20, api_key: str = Depends(get_api_key)):
    """List user's recent agent runs."""
    conn = get_db()
    try:
        rows = db_fetchall(conn,
            f"SELECT id, agent_type, task_description, status, created_at, completed_at FROM agents WHERE {USER_KEY_COL} = ? ORDER BY created_at DESC LIMIT ?",
            (api_key, limit),
        )
    finally:
        conn.close()
    return {"agents": [
        {"id": r[0], "agent_type": r[1], "task_description": r[2], "status": r[3], "created_at": r[4], "completed_at": r[5]}
        for r in rows
    ]}


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

    asyncio.create_task(execute_task(agent_id, req.agent_type, req.task_description, api_key, model=req.model))

    return {
        "agent_id": agent_id,
        "agent_type": req.agent_type,
        "agent_name": AGENTS[req.agent_type]["name"],
        "model": req.model or CLAUDE_MODEL,
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


# ─── MODEL ENDPOINTS ─────────────────────────────────────

@app.get("/api/v1/models")
async def list_models():
    """List all available LLM providers and models."""
    if not MULTI_MODEL or not model_router:
        return {
            "providers": [{
                "provider": "anthropic",
                "name": "Anthropic",
                "available": bool(ANTHROPIC_API_KEY),
                "models": [{"model_id": CLAUDE_MODEL, "name": "Claude Haiku 4.5"}],
                "default_model": CLAUDE_MODEL,
            }],
            "default_model": CLAUDE_MODEL,
        }
    providers = model_router.get_available_providers()
    return {
        "providers": providers,
        "available_count": sum(1 for p in providers if p["available"]),
        "total_models": sum(len(p["models"]) for p in providers),
    }


@app.get("/api/v1/models/available")
async def list_available_models():
    """List only models that have API keys configured and are ready to use."""
    if not MULTI_MODEL or not model_router:
        return {"models": [{"model_id": CLAUDE_MODEL, "provider": "anthropic", "name": "Claude Haiku 4.5"}]}
    providers = model_router.get_available_providers()
    models = []
    for p in providers:
        if p["available"]:
            for m in p["models"]:
                m["provider"] = p["provider"]
                m["provider_name"] = p["name"]
                models.append(m)
    return {"models": models, "count": len(models)}


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


# ─── VOICE ENDPOINTS ─────────────────────────────────────

@app.get("/api/v1/voice/status")
async def voice_status():
    if not VOICE_AVAILABLE or not voice_pipeline:
        return {"stt": {"available": False}, "tts": {"available": False}}
    return await voice_pipeline.get_voice_status()


@app.get("/api/v1/voice/voices")
async def list_voices():
    return {"voices": VOICE_OPTIONS}


@app.post("/api/v1/voice/transcribe")
async def transcribe_audio(request: Request, api_key: str = Depends(get_api_key)):
    """Upload audio and get transcription. Send raw audio bytes in request body."""
    if not VOICE_AVAILABLE or not voice_pipeline:
        raise HTTPException(status_code=503, detail="Voice not available")
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No audio data")
    result = await voice_pipeline.stt.transcribe(audio_bytes)
    return result


@app.post("/api/v1/voice/synthesize")
async def synthesize_speech(request: Request, api_key: str = Depends(get_api_key)):
    """Convert text to speech. Returns audio bytes."""
    if not VOICE_AVAILABLE or not voice_pipeline:
        raise HTTPException(status_code=503, detail="Voice not available")
    body = await request.json()
    text = body.get("text", "")
    voice = body.get("voice")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    result = await voice_pipeline.tts.synthesize(text, voice=voice)
    if result.get("error") or not result.get("audio_bytes"):
        raise HTTPException(status_code=500, detail=result.get("error", "TTS failed"))
    from fastapi.responses import Response
    return Response(
        content=result["audio_bytes"],
        media_type=f"audio/{result.get('format', 'opus')}",
        headers={"X-Voice-Provider": result.get("provider", ""), "X-Voice-Name": result.get("voice", "")},
    )


@app.post("/api/v1/voice/deploy")
async def voice_deploy_agent(request: Request, api_key: str = Depends(get_api_key)):
    """Send voice audio, get agent result as text + voice. Full pipeline."""
    if not VOICE_AVAILABLE or not voice_pipeline:
        raise HTTPException(status_code=503, detail="Voice not available")

    # Parse multipart or raw audio
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        body = await request.json()
        audio_b64 = body.get("audio_base64", "")
        if not audio_b64:
            raise HTTPException(status_code=400, detail="audio_base64 required")
        audio_bytes = base64.b64decode(audio_b64)
        agent_type = body.get("agent_type", "research")
        model = body.get("model")
        voice = body.get("voice")
        respond_voice = body.get("voice_response", True)
    else:
        audio_bytes = await request.body()
        agent_type = request.query_params.get("agent_type", "research")
        model = request.query_params.get("model")
        voice = request.query_params.get("voice")
        respond_voice = request.query_params.get("voice_response", "true") == "true"

    # Transcribe
    transcript = await voice_pipeline.stt.transcribe(audio_bytes)
    if not transcript.get("text"):
        raise HTTPException(status_code=400, detail=f"Transcription failed: {transcript.get('error', '')}")

    task = transcript["text"]

    # Deploy agent
    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,
            f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
            (agent_id, api_key, agent_type, task, now),
        )
        conn.commit()
    finally:
        conn.close()

    await execute_task(agent_id, agent_type, task, api_key, model=model)

    # Get result
    conn = get_db()
    try:
        row = conn.execute("SELECT result, status FROM agents WHERE id = ?", (agent_id,)).fetchone()
    finally:
        conn.close()
    result_text = row[0] if row else "No result"

    response = {
        "agent_id": agent_id,
        "transcript": task,
        "stt_provider": transcript.get("provider", ""),
        "result": result_text,
    }

    # Synthesize voice response if requested
    if respond_voice:
        tts_result = await voice_pipeline.tts.synthesize(result_text[:2000], voice=voice)
        if tts_result.get("audio_bytes"):
            response["audio_base64"] = base64.b64encode(tts_result["audio_bytes"]).decode()
            response["audio_format"] = tts_result.get("format", "opus")
            response["tts_provider"] = tts_result.get("provider", "")

    return response


@app.post("/api/v1/voice/enable/{channel_id}")
async def enable_voice_response(channel_id: str, api_key: str = Depends(get_api_key)):
    if not VOICE_AVAILABLE or not voice_pipeline:
        raise HTTPException(status_code=503, detail="Voice not available")
    voice_pipeline.enable_voice_response(channel_id)
    return {"status": "voice_response_enabled", "channel_id": channel_id}


@app.post("/api/v1/voice/disable/{channel_id}")
async def disable_voice_response(channel_id: str, api_key: str = Depends(get_api_key)):
    if not VOICE_AVAILABLE or not voice_pipeline:
        raise HTTPException(status_code=503, detail="Voice not available")
    voice_pipeline.disable_voice_response(channel_id)
    return {"status": "voice_response_disabled", "channel_id": channel_id}


import base64

# ─── MARKETPLACE ENDPOINTS ───────────────────────────────

class CreateAgentRequest(BaseModel):
    name: str
    description: str
    system_prompt: str
    category: str = "general"
    tags: list = []
    tools: list = []
    model_preference: str = ""
    icon: str = "🤖"
    price_usd: float = 0.0
    creator_name: str = "anonymous"
    long_description: str = ""


class ReviewRequest(BaseModel):
    rating: int
    review_text: str = ""


class SkillPackRequest(BaseModel):
    name: str
    description: str
    agent_ids: list = []
    workflow_configs: list = []
    mcp_tool_configs: list = []
    price_usd: float = 0.0
    creator_name: str = "anonymous"


@app.post("/api/v1/marketplace/agents")
async def create_marketplace_agent(req: CreateAgentRequest, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    result = await marketplace.create_agent(
        creator_key=api_key, name=req.name, description=req.description,
        system_prompt=req.system_prompt, category=req.category, tags=req.tags,
        tools=req.tools, model_preference=req.model_preference, icon=req.icon,
        price_usd=req.price_usd, creator_name=req.creator_name,
        long_description=req.long_description,
    )
    return result


@app.get("/api/v1/marketplace/agents")
async def browse_marketplace(category: str = None, search: str = None, sort: str = "popular", limit: int = 20, offset: int = 0):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        return {"agents": [], "starters": STARTER_AGENTS}
    agents = await marketplace.browse(category=category, search=search, sort=sort, limit=limit, offset=offset)
    return {"agents": agents}


@app.get("/api/v1/marketplace/agents/{slug_or_id}")
async def get_marketplace_agent(slug_or_id: str):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    agent = await marketplace.get_agent_detail(slug_or_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.post("/api/v1/marketplace/agents/{agent_id}/publish")
async def publish_agent(agent_id: str, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    return await marketplace.publish_agent(agent_id, api_key)


@app.post("/api/v1/marketplace/agents/{agent_id}/unpublish")
async def unpublish_agent(agent_id: str, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    return await marketplace.unpublish_agent(agent_id, api_key)


@app.put("/api/v1/marketplace/agents/{agent_id}")
async def update_marketplace_agent(agent_id: str, request: Request, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    updates = await request.json()
    return await marketplace.update_agent(agent_id, api_key, updates)


@app.post("/api/v1/marketplace/agents/{agent_id}/install")
async def install_marketplace_agent(agent_id: str, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    result = await marketplace.install_agent(api_key, agent_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/v1/marketplace/agents/{agent_id}/uninstall")
async def uninstall_marketplace_agent(agent_id: str, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    return await marketplace.uninstall_agent(api_key, agent_id)


@app.get("/api/v1/marketplace/installed")
async def list_installed(api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        return {"agents": []}
    agents = await marketplace.get_installed(api_key)
    return {"agents": agents}


@app.post("/api/v1/marketplace/agents/{agent_id}/deploy")
async def deploy_marketplace_agent(agent_id: str, request: Request, api_key: str = Depends(get_api_key)):
    """Deploy an installed marketplace agent with a task."""
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    body = await request.json()
    task = body.get("task_description", "")
    model = body.get("model")
    if not task:
        raise HTTPException(status_code=400, detail="task_description required")

    # Verify installed
    installed = await marketplace.get_installed(api_key)
    agent_match = next((a for a in installed if a["agent_id"] == agent_id), None)
    if not agent_match:
        raise HTTPException(status_code=403, detail="Agent not installed. Install it first.")

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,
            f"INSERT INTO agents (id, {USER_KEY_COL}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
            (run_id, api_key, f"mp:{agent_match['slug']}", task, now),
        )
        conn.commit()
    finally:
        conn.close()

    asyncio.create_task(execute_task(run_id, f"mp:{agent_match['slug']}", task, api_key, model=model))

    return {
        "agent_id": run_id,
        "marketplace_agent": agent_match["name"],
        "model": model or agent_match.get("model_preference") or "default",
        "status": "running",
    }


@app.post("/api/v1/marketplace/agents/{agent_id}/review")
async def review_agent(agent_id: str, req: ReviewRequest, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    result = await marketplace.add_review(agent_id, api_key, req.rating, req.review_text)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/v1/marketplace/agents/{agent_id}/reviews")
async def get_agent_reviews(agent_id: str):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        return {"reviews": []}
    return {"reviews": await marketplace.get_reviews(agent_id)}


@app.get("/api/v1/marketplace/my-agents")
async def my_marketplace_agents(api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        return {"agents": []}
    return {"agents": await marketplace.get_my_agents(api_key)}


@app.get("/api/v1/marketplace/earnings")
async def my_earnings(api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        return {"total_earned": 0, "total_sales": 0, "recent_sales": []}
    return await marketplace.get_earnings(api_key)


@app.post("/api/v1/marketplace/skill-packs")
async def create_skill_pack(req: SkillPackRequest, api_key: str = Depends(get_api_key)):
    if not MARKETPLACE_AVAILABLE or not marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not loaded")
    return await marketplace.create_skill_pack(
        creator_key=api_key, name=req.name, description=req.description,
        agent_ids=req.agent_ids, workflow_configs=req.workflow_configs,
        mcp_tool_configs=req.mcp_tool_configs, price_usd=req.price_usd,
        creator_name=req.creator_name,
    )


@app.get("/api/v1/marketplace/stats")
async def marketplace_stats():
    if not MARKETPLACE_AVAILABLE or not marketplace:
        return {"published_agents": 0, "total_installs": 0, "active_creators": 0}
    return await marketplace.get_marketplace_stats()


@app.get("/api/v1/marketplace/categories")
async def marketplace_categories():
    return {"categories": [
        {"id": "crypto-defi", "name": "Crypto & DeFi", "icon": "💎"},
        {"id": "coding-dev", "name": "Coding & Dev", "icon": "💻"},
        {"id": "writing-content", "name": "Writing & Content", "icon": "✍️"},
        {"id": "data-research", "name": "Data & Research", "icon": "📊"},
        {"id": "business-strategy", "name": "Business & Strategy", "icon": "📈"},
        {"id": "productivity", "name": "Productivity", "icon": "⚡"},
        {"id": "security", "name": "Security", "icon": "🔒"},
        {"id": "marketing", "name": "Marketing", "icon": "📢"},
    ]}


@app.get("/api/v1/marketplace/featured")
async def marketplace_featured():
    """Get starter/featured agents."""
    return {"starters": STARTER_AGENTS}


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
    message = data.get("message", {})

    # Handle voice messages
    voice = message.get("voice") or message.get("audio")
    if voice and VOICE_AVAILABLE and voice_pipeline:
        asyncio.create_task(_handle_telegram_voice(message, voice))
        return {"ok": True}

    if CHANNELS_LOADED:
        msg = parse_telegram_webhook(data)
        if msg:
            asyncio.create_task(command_router.handle(msg))
    else:
        if message.get("text"):
            asyncio.create_task(handle_telegram_message(message))
    return {"ok": True}


async def _handle_telegram_voice(message: dict, voice_info: dict):
    """Process incoming Telegram voice message."""
    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return
    try:
        from channels import send_telegram
        await send_telegram(chat_id, "🎙️ Transcribing your voice...")

        # Download voice file
        file_id = voice_info.get("file_id", "")
        audio_bytes = await download_telegram_voice(file_id)
        if not audio_bytes:
            await send_telegram(chat_id, "❌ Failed to download voice message")
            return

        # Transcribe
        result = await voice_pipeline.process_voice_message(
            audio_bytes=audio_bytes,
            platform="telegram",
            channel_id=str(chat_id),
            user_id=str(message.get("from", {}).get("id", "")),
        )

        if result.get("error") or not result.get("text"):
            await send_telegram(chat_id, f"❌ Transcription failed: {result.get('error', 'unknown')}")
            return

        text = result["text"]
        await send_telegram(chat_id, f"📝 *Heard:* {text}")

        # Route transcribed text through command router
        if CHANNELS_LOADED:
            from channels import ChannelMessage
            msg = ChannelMessage(
                platform="telegram",
                channel_id=str(chat_id),
                user_id=str(message.get("from", {}).get("id", "")),
                text=text,
            )
            await command_router.handle(msg)

            # If voice response is enabled, also send TTS of the result
            if voice_pipeline.is_voice_enabled(str(chat_id)):
                # Get the agent result from DB
                conn = get_db()
                try:
                    row = conn.execute(
                        f"SELECT result FROM agents WHERE {USER_KEY_COL} = ? ORDER BY created_at DESC LIMIT 1",
                        (f"telegram:{chat_id}",),
                    ).fetchone()
                finally:
                    conn.close()
                if row and row[0]:
                    await voice_pipeline.synthesize_and_send(
                        text=row[0][:2000],
                        platform="telegram",
                        channel_id=str(chat_id),
                    )

    except Exception as e:
        logger.error(f"Voice handler error: {e}")
        try:
            from channels import send_telegram
            await send_telegram(chat_id, f"❌ Voice processing error: {str(e)[:200]}")
        except Exception:
            pass


@app.post("/api/v1/discord/webhook")
async def discord_webhook(request: Request):
    """Discord Interactions endpoint — set this URL in Discord Developer Portal."""
    if not DISCORD_ENABLED or not CHANNELS_LOADED:
        return JSONResponse({"error": "Discord not configured"}, status_code=503)
    data = await request.json()

    # Discord verification ping
    if data.get("type") == 1:
        return JSONResponse({"type": 1})

    msg = parse_discord_webhook(data)
    if msg:
        # For slash commands, acknowledge immediately then process
        if data.get("type") == 2:
            asyncio.create_task(command_router.handle(msg))
            return JSONResponse({"type": 5})  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
        asyncio.create_task(command_router.handle(msg))
    return {"ok": True}


@app.post("/api/v1/slack/webhook")
async def slack_webhook(request: Request):
    """Slack Events API endpoint — set this URL in Slack App settings."""
    data = await request.json()

    # Slack URL verification challenge
    if data.get("type") == "url_verification":
        return JSONResponse({"challenge": data.get("challenge", "")})

    if not SLACK_ENABLED or not CHANNELS_LOADED:
        return {"ok": True}

    msg = parse_slack_webhook(data)
    if msg:
        asyncio.create_task(command_router.handle(msg))
    return {"ok": True}


@app.get("/api/v1/channels")
async def list_channels():
    """List all configured messaging channels."""
    if CHANNELS_LOADED:
        return get_channel_status()
    return {
        "telegram": {"enabled": TELEGRAM_ENABLED, "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", ""))},
        "discord": {"enabled": False, "configured": False},
        "slack": {"enabled": False, "configured": False},
    }


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
<title>APEX SWARM v4 — Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#050508;--surface:#0c0c14;--surface2:#13131f;--surface3:#1a1a2a;
  --border:#252538;--border2:#353548;
  --text:#e4e4f0;--text2:#8888a8;--text3:#5555708;
  --green:#00ff88;--green2:#00cc6a;--greenbg:rgba(0,255,136,0.08);
  --red:#ff4466;--redbg:rgba(255,68,102,0.08);
  --blue:#4488ff;--bluebg:rgba(68,136,255,0.08);
  --purple:#8855ff;--purplebg:rgba(136,85,255,0.08);
  --orange:#ff8844;--orangebg:rgba(255,136,68,0.08);
  --yellow:#ffcc00;
  --radius:10px;--radius2:16px;
}
body{background:var(--bg);color:var(--text);font-family:'Outfit',sans-serif;overflow-x:hidden;min-height:100vh}
a{color:var(--green);text-decoration:none}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--surface)}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

/* ─── LAYOUT ─── */
.app{display:grid;grid-template-columns:240px 1fr;grid-template-rows:60px 1fr;height:100vh}
.topbar{grid-column:1/-1;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 24px;z-index:100}
.sidebar{background:var(--surface);border-right:1px solid var(--border);padding:16px 12px;overflow-y:auto}
.main{overflow-y:auto;padding:24px;background:var(--bg)}

/* ─── TOPBAR ─── */
.logo{font-family:'Space Mono',monospace;font-weight:700;font-size:18px;color:var(--green);letter-spacing:-0.5px}
.logo span{color:var(--text2);font-weight:400;font-size:13px;margin-left:8px}
.topbar-right{display:flex;align-items:center;gap:16px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.api-key-input{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:6px 12px;border-radius:6px;font-size:12px;width:200px;font-family:'Space Mono',monospace}
.api-key-input::placeholder{color:var(--text2)}

/* ─── SIDEBAR ─── */
.nav-section{margin-bottom:24px}
.nav-label{font-size:10px;text-transform:uppercase;letter-spacing:2px;color:var(--text2);padding:0 12px;margin-bottom:8px}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;cursor:pointer;font-size:14px;color:var(--text2);transition:all 0.15s}
.nav-item:hover{background:var(--surface2);color:var(--text)}
.nav-item.active{background:var(--greenbg);color:var(--green);font-weight:500}
.nav-icon{font-size:18px;width:24px;text-align:center}
.nav-badge{margin-left:auto;background:var(--green);color:var(--bg);font-size:10px;font-weight:700;padding:2px 6px;border-radius:10px}

/* ─── CARDS ─── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius2);padding:20px;transition:border-color 0.2s}
.card:hover{border-color:var(--border2)}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.card-title{font-weight:600;font-size:16px}
.card-subtitle{color:var(--text2);font-size:13px;margin-top:4px}

/* ─── BUTTONS ─── */
.btn{padding:8px 16px;border-radius:8px;border:none;font-family:'Outfit',sans-serif;font-weight:500;font-size:13px;cursor:pointer;transition:all 0.15s;display:inline-flex;align-items:center;gap:6px}
.btn-primary{background:var(--green);color:var(--bg)}
.btn-primary:hover{background:var(--green2);transform:translateY(-1px)}
.btn-secondary{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{border-color:var(--green);color:var(--green)}
.btn-danger{background:var(--redbg);color:var(--red);border:1px solid transparent}
.btn-danger:hover{border-color:var(--red)}
.btn-sm{padding:5px 10px;font-size:12px}
.btn-lg{padding:12px 24px;font-size:15px}

/* ─── GRID ─── */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}

/* ─── STAT CARDS ─── */
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px}
.stat-value{font-family:'Space Mono',monospace;font-size:28px;font-weight:700;color:var(--green)}
.stat-label{color:var(--text2);font-size:12px;margin-top:4px;text-transform:uppercase;letter-spacing:1px}

/* ─── MARKETPLACE ─── */
.mp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.mp-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius2);padding:20px;cursor:pointer;transition:all 0.2s;position:relative;overflow:hidden}
.mp-card:hover{border-color:var(--green);transform:translateY(-2px);box-shadow:0 8px 32px rgba(0,255,136,0.06)}
.mp-icon{font-size:32px;margin-bottom:12px}
.mp-name{font-weight:600;font-size:16px;margin-bottom:4px}
.mp-desc{color:var(--text2);font-size:13px;line-height:1.5;margin-bottom:12px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.mp-meta{display:flex;align-items:center;gap:12px;font-size:12px;color:var(--text2)}
.mp-tag{background:var(--surface2);padding:3px 8px;border-radius:4px;font-size:11px;color:var(--text2)}
.mp-price{font-family:'Space Mono',monospace;font-weight:700;color:var(--green)}
.mp-rating{color:var(--yellow)}
.mp-installs{color:var(--text2)}
.mp-category-bar{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.mp-cat-btn{padding:6px 14px;border-radius:20px;border:1px solid var(--border);background:transparent;color:var(--text2);font-size:13px;cursor:pointer;transition:all 0.15s;font-family:'Outfit',sans-serif}
.mp-cat-btn:hover,.mp-cat-btn.active{border-color:var(--green);color:var(--green);background:var(--greenbg)}

/* ─── DEPLOY PANEL ─── */
.deploy-form{display:flex;flex-direction:column;gap:12px}
.form-group{display:flex;flex-direction:column;gap:6px}
.form-label{font-size:12px;color:var(--text2);text-transform:uppercase;letter-spacing:1px}
.form-input,.form-select,.form-textarea{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:8px;font-family:'Outfit',sans-serif;font-size:14px;outline:none;transition:border-color 0.15s}
.form-input:focus,.form-select:focus,.form-textarea:focus{border-color:var(--green)}
.form-textarea{min-height:100px;resize:vertical}
.form-select{cursor:pointer}

/* ─── AGENT LIST ─── */
.agent-row{display:flex;align-items:center;gap:16px;padding:12px 16px;border-bottom:1px solid var(--border);transition:background 0.1s}
.agent-row:hover{background:var(--surface2)}
.agent-status{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.agent-status.running{background:var(--green);animation:pulse 2s infinite}
.agent-status.completed{background:var(--blue)}
.agent-status.failed{background:var(--red)}
.agent-name{font-weight:500;font-size:14px;flex:1}
.agent-task{color:var(--text2);font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.agent-time{color:var(--text2);font-size:12px;font-family:'Space Mono',monospace}

/* ─── EVENT FEED ─── */
.event{padding:10px 16px;border-left:3px solid var(--border);margin-bottom:8px;font-size:13px;background:var(--surface);border-radius:0 8px 8px 0}
.event.agent-started{border-left-color:var(--green)}
.event.agent-completed{border-left-color:var(--blue)}
.event.agent-failed{border-left-color:var(--red)}
.event.daemon-alert{border-left-color:var(--orange)}
.event-time{color:var(--text2);font-size:11px;font-family:'Space Mono',monospace}
.event-msg{margin-top:4px}

/* ─── MODAL ─── */
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:1000;backdrop-filter:blur(4px)}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius2);padding:28px;max-width:600px;width:90%;max-height:80vh;overflow-y:auto}
.modal-title{font-size:20px;font-weight:700;margin-bottom:16px}
.modal-close{position:absolute;top:16px;right:16px;background:none;border:none;color:var(--text2);font-size:20px;cursor:pointer}

/* ─── WORKFLOW BUILDER ─── */
.wf-node{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:16px;position:relative}
.wf-node-title{font-weight:600;font-size:14px;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.wf-connector{width:2px;height:24px;background:var(--border);margin:0 auto}
.wf-arrow{text-align:center;color:var(--text2);font-size:20px;margin:4px 0}

/* ─── TABS ─── */
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:20px}
.tab{padding:10px 20px;font-size:14px;color:var(--text2);cursor:pointer;border-bottom:2px solid transparent;transition:all 0.15s}
.tab:hover{color:var(--text)}
.tab.active{color:var(--green);border-bottom-color:var(--green)}

/* ─── RESPONSIVE ─── */
@media(max-width:768px){.app{grid-template-columns:1fr}.sidebar{display:none}.grid-3,.grid-4{grid-template-columns:1fr 1fr}.mp-grid{grid-template-columns:1fr}}

/* ─── ANIMATIONS ─── */
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.fade-in{animation:fadeIn 0.3s ease}
@keyframes slideIn{from{opacity:0;transform:translateX(-20px)}to{opacity:1;transform:translateX(0)}}
.slide-in{animation:slideIn 0.3s ease}

/* ─── LOADING ─── */
.spinner{width:20px;height:20px;border:2px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin 0.6s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}

.empty-state{text-align:center;padding:60px 20px;color:var(--text2)}
.empty-state-icon{font-size:48px;margin-bottom:16px;opacity:0.5}
.empty-state-text{font-size:15px;margin-bottom:20px}
</style>
</head>
<body>

<div class="app" id="app">
  <!-- TOPBAR -->
  <div class="topbar">
    <div class="logo">APEX SWARM <span>v__VERSION__</span></div>
    <div class="topbar-right">
      <div style="display:flex;align-items:center;gap:8px">
        <div class="status-dot" id="statusDot"></div>
        <span style="font-size:12px;color:var(--text2)" id="statusText">Connected</span>
      </div>
      <input type="password" class="api-key-input" id="apiKeyInput" placeholder="API Key" />
      <button class="btn btn-primary btn-sm" onclick="saveApiKey()">Connect</button>
    </div>
  </div>

  <!-- SIDEBAR -->
  <div class="sidebar">
    <div class="nav-section">
      <div class="nav-label">Command Center</div>
      <div class="nav-item active" data-page="overview" onclick="navigate('overview')">
        <span class="nav-icon">👁️</span> God Eye
      </div>
      <div class="nav-item" data-page="deploy" onclick="navigate('deploy')">
        <span class="nav-icon">⚡</span> Deploy Agent
      </div>
      <div class="nav-item" data-page="agents" onclick="navigate('agents')">
        <span class="nav-icon">🤖</span> My Agents
      </div>
      <div class="nav-item" data-page="feed" onclick="navigate('feed')">
        <span class="nav-icon">📡</span> Live Feed
      </div>
    </div>
    <div class="nav-section">
      <div class="nav-label">Marketplace</div>
      <div class="nav-item" data-page="marketplace" onclick="navigate('marketplace')">
        <span class="nav-icon">🏪</span> Browse Agents
        <span class="nav-badge" id="mpBadge">NEW</span>
      </div>
      <div class="nav-item" data-page="create-agent" onclick="navigate('create-agent')">
        <span class="nav-icon">🛠️</span> Create Agent
      </div>
      <div class="nav-item" data-page="my-store" onclick="navigate('my-store')">
        <span class="nav-icon">💰</span> My Store
      </div>
    </div>
    <div class="nav-section">
      <div class="nav-label">Automation</div>
      <div class="nav-item" data-page="workflows" onclick="navigate('workflows')">
        <span class="nav-icon">⚙️</span> Workflows
      </div>
      <div class="nav-item" data-page="daemons" onclick="navigate('daemons')">
        <span class="nav-icon">👁️</span> Daemons
      </div>
      <div class="nav-item" data-page="schedules" onclick="navigate('schedules')">
        <span class="nav-icon">🕐</span> Schedules
      </div>
    </div>
    <div class="nav-section">
      <div class="nav-label">System</div>
      <div class="nav-item" data-page="models" onclick="navigate('models')">
        <span class="nav-icon">🧠</span> Models
      </div>
      <div class="nav-item" data-page="channels" onclick="navigate('channels')">
        <span class="nav-icon">💬</span> Channels
      </div>
      <div class="nav-item" data-page="settings" onclick="navigate('settings')">
        <span class="nav-icon">⚙️</span> Settings
      </div>
    </div>
  </div>

  <!-- MAIN -->
  <div class="main" id="mainContent"></div>
</div>

<script>
// ─── STATE ───────────────────────────────────────
let API_KEY = localStorage.getItem('apex_api_key') || '';
let BASE_URL = window.location.origin;
let currentPage = 'overview';
let godEyeData = {};
let eventSource = null;
let liveEvents = [];

// ─── API ─────────────────────────────────────────
async function api(path, opts = {}) {
  const headers = { 'X-Api-Key': API_KEY, 'Content-Type': 'application/json', ...opts.headers };
  try {
    const r = await fetch(BASE_URL + path, { ...opts, headers });
    return await r.json();
  } catch(e) { console.error('API Error:', e); return { error: e.message }; }
}

function saveApiKey() {
  API_KEY = document.getElementById('apiKeyInput').value;
  localStorage.setItem('apex_api_key', API_KEY);
  navigate(currentPage);
}

// ─── NAVIGATION ──────────────────────────────────
function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
  const main = document.getElementById('mainContent');
  main.innerHTML = '<div style="display:flex;justify-content:center;padding:40px"><div class="spinner"></div></div>';
  const pages = {overview:renderOverview,deploy:renderDeploy,agents:renderAgents,feed:renderFeed,marketplace:renderMarketplace,'create-agent':renderCreateAgent,'my-store':renderMyStore,workflows:renderWorkflows,daemons:renderDaemons,models:renderModels,channels:renderChannels,settings:renderSettings,schedules:renderSchedules};
  (pages[page] || renderOverview)();
}

// ─── GOD EYE ─────────────────────────────────────
async function renderOverview() {
  const [health, godEye, mpStats] = await Promise.all([
    api('/api/v1/health'), api('/api/v1/god-eye'), api('/api/v1/marketplace/stats')
  ]);
  const ge = godEye || {};
  const mp = mpStats || {};
  const h = health || {};
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">👁️ God Eye — Live Overview</h2>
      <div class="grid-4" style="margin-bottom:24px">
        <div class="stat"><div class="stat-value">${ge.active_agents||0}</div><div class="stat-label">Active Agents</div></div>
        <div class="stat"><div class="stat-value">${ge.active_daemons||0}</div><div class="stat-label">Daemons</div></div>
        <div class="stat"><div class="stat-value">${ge.total_events||0}</div><div class="stat-label">Total Events</div></div>
        <div class="stat"><div class="stat-value" style="color:var(--blue)">${mp.published_agents||0}</div><div class="stat-label">Marketplace Agents</div></div>
      </div>
      <div class="grid-2" style="margin-bottom:24px">
        <div class="card">
          <div class="card-header"><div class="card-title">System Status</div></div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            ${Object.entries({Tools:h.tools,Chains:h.chains,Knowledge:h.knowledge,'Mission Control':h.mission_control,Memory:h.swarm_memory,MCP:h.mcp_registry,'Multi-Model':h.multi_model,Marketplace:h.marketplace,Voice:h.voice,Workflows:h.workflows}).map(([k,v])=>`<div style="display:flex;align-items:center;gap:8px;font-size:13px;padding:6px 0"><span>${v?'🟢':'🔴'}</span>${k}</div>`).join('')}
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">Recent Events</div></div>
          <div id="overviewEvents" style="max-height:250px;overflow-y:auto"></div>
        </div>
      </div>
      <div class="grid-3">
        <div class="card" style="cursor:pointer" onclick="navigate('deploy')">
          <div style="font-size:32px;margin-bottom:8px">⚡</div>
          <div class="card-title">Deploy Agent</div>
          <div class="card-subtitle">Deploy any of 66+ agents instantly</div>
        </div>
        <div class="card" style="cursor:pointer" onclick="navigate('marketplace')">
          <div style="font-size:32px;margin-bottom:8px">🏪</div>
          <div class="card-title">Marketplace</div>
          <div class="card-subtitle">${mp.published_agents||0} agents · ${mp.total_installs||0} installs</div>
        </div>
        <div class="card" style="cursor:pointer" onclick="navigate('workflows')">
          <div style="font-size:32px;margin-bottom:8px">⚙️</div>
          <div class="card-title">Workflows</div>
          <div class="card-subtitle">Automate with triggers & actions</div>
        </div>
      </div>
    </div>`;
  loadOverviewEvents();
}

async function loadOverviewEvents() {
  const el = document.getElementById('overviewEvents');
  if (!el) return;
  if (liveEvents.length === 0) { el.innerHTML = '<div style="color:var(--text2);font-size:13px;padding:8px">No events yet. Deploy an agent to see activity.</div>'; return; }
  el.innerHTML = liveEvents.slice(-8).reverse().map(e => `<div class="event ${e.event_type}" style="margin-bottom:6px"><div class="event-time">${new Date(e.timestamp).toLocaleTimeString()}</div><div class="event-msg">${e.agent_name||e.agent_type}: ${(e.message||'').slice(0,100)}</div></div>`).join('');
}

// ─── DEPLOY ──────────────────────────────────────
async function renderDeploy() {
  const agents = await api('/api/v1/agents');
  const models = await api('/api/v1/models/available');
  const agentList = (agents.agents||[]).map(a => `<option value="${a.type}">${a.name} — ${a.category}</option>`).join('');
  const modelList = (models.models||[]).map(m => `<option value="${m.model_id}">${m.provider_name}: ${m.name}</option>`).join('');
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">⚡ Deploy Agent</h2>
      <div class="grid-2">
        <div class="card">
          <div class="deploy-form">
            <div class="form-group">
              <label class="form-label">Agent Type</label>
              <select class="form-select" id="deployAgent">${agentList}</select>
            </div>
            <div class="form-group">
              <label class="form-label">Model (optional)</label>
              <select class="form-select" id="deployModel"><option value="">Default (Claude Haiku)</option>${modelList}</select>
            </div>
            <div class="form-group">
              <label class="form-label">Task Description</label>
              <textarea class="form-textarea" id="deployTask" placeholder="What should this agent do?"></textarea>
            </div>
            <button class="btn btn-primary btn-lg" onclick="deployAgent()" id="deployBtn">⚡ Deploy</button>
            <div id="deployResult" style="margin-top:12px"></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title" style="margin-bottom:12px">Recent Deploys</div>
          <div id="recentDeploys"></div>
        </div>
      </div>
    </div>`;
  loadRecentDeploys();
}

async function deployAgent() {
  const btn = document.getElementById('deployBtn');
  btn.innerHTML = '<div class="spinner"></div> Deploying...';
  btn.disabled = true;
  const data = { agent_type: document.getElementById('deployAgent').value, task_description: document.getElementById('deployTask').value };
  const model = document.getElementById('deployModel').value;
  if (model) data.model = model;
  const r = await api('/api/v1/deploy', { method: 'POST', body: JSON.stringify(data) });
  btn.innerHTML = '⚡ Deploy';
  btn.disabled = false;
  const el = document.getElementById('deployResult');
  if (r.agent_id) {
    el.innerHTML = `<div style="background:var(--greenbg);border:1px solid var(--green);border-radius:8px;padding:12px;font-size:13px">✅ <strong>${r.agent_name}</strong> deployed<br><code style="font-size:11px">${r.agent_id}</code></div>`;
    loadRecentDeploys();
  } else {
    el.innerHTML = `<div style="background:var(--redbg);border:1px solid var(--red);border-radius:8px;padding:12px;font-size:13px">❌ ${r.detail||r.error||'Deploy failed'}</div>`;
  }
}

async function loadRecentDeploys() {
  const el = document.getElementById('recentDeploys');
  if (!el) return;
  const r = await api('/api/v1/agents/recent?limit=10');
  const agents = r.agents || [];
  if (!agents.length) { el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🤖</div><div class="empty-state-text">No agents deployed yet</div></div>'; return; }
  el.innerHTML = agents.map(a => `<div class="agent-row"><div class="agent-status ${a.status}"></div><div class="agent-name">${a.agent_type}</div><div class="agent-task">${(a.task_description||'').slice(0,60)}</div><div class="agent-time">${a.status}</div></div>`).join('');
}

// ─── MY AGENTS ───────────────────────────────────
async function renderAgents() {
  const r = await api('/api/v1/agents/recent?limit=30');
  const agents = r.agents || [];
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">🤖 My Agents</h2>
      <div class="card">${agents.length ? agents.map(a => `
        <div class="agent-row" style="cursor:pointer" onclick="showAgentResult('${a.id}')">
          <div class="agent-status ${a.status}"></div>
          <div class="agent-name">${a.agent_type}</div>
          <div class="agent-task">${(a.task_description||'').slice(0,80)}</div>
          <div class="agent-time">${a.status}</div>
        </div>`).join('') : '<div class="empty-state"><div class="empty-state-icon">🤖</div><div class="empty-state-text">No agents yet. Deploy one!</div><button class="btn btn-primary" onclick="navigate(\'deploy\')">Deploy Agent</button></div>'}</div>
    </div>`;
}

async function showAgentResult(id) {
  const r = await api('/api/v1/status/' + id);
  if (!r.result) return;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.onclick = e => { if(e.target===overlay) overlay.remove(); };
  overlay.innerHTML = `<div class="modal"><div class="modal-title">${r.agent_type} — Result</div><div style="color:var(--text2);font-size:12px;margin-bottom:12px">Status: ${r.status}</div><div style="white-space:pre-wrap;font-size:14px;line-height:1.6;max-height:60vh;overflow-y:auto">${(r.result||'').replace(/</g,'&lt;')}</div><button class="btn btn-secondary" style="margin-top:16px" onclick="this.closest('.modal-overlay').remove()">Close</button></div>`;
  document.body.appendChild(overlay);
}

// ─── LIVE FEED ───────────────────────────────────
function renderFeed() {
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">📡 Live Event Feed</h2>
      <div class="card" id="feedContainer" style="min-height:400px;max-height:70vh;overflow-y:auto">
        ${liveEvents.length ? liveEvents.slice().reverse().map(e => `<div class="event ${e.event_type}"><div class="event-time">${new Date(e.timestamp).toLocaleTimeString()}</div><div class="event-msg"><strong>${e.agent_name||e.agent_type||'system'}</strong>: ${(e.message||'').slice(0,200)}</div></div>`).join('') : '<div class="empty-state"><div class="empty-state-icon">📡</div><div class="empty-state-text">Listening for events...</div><div class="spinner"></div></div>'}
      </div>
    </div>`;
}

// ─── MARKETPLACE ─────────────────────────────────
let mpCategory = null;
async function renderMarketplace() {
  const [agents, cats, featured] = await Promise.all([
    api('/api/v1/marketplace/agents' + (mpCategory ? '?category='+mpCategory : '')),
    api('/api/v1/marketplace/categories'),
    api('/api/v1/marketplace/featured')
  ]);
  const categories = cats.categories || [];
  const starters = featured.starters || [];
  const mpAgents = agents.agents || [];
  const allAgents = [...mpAgents, ...(mpAgents.length === 0 ? starters.map((s,i) => ({...s, agent_id:'starter-'+i, slug:'starter-'+i, is_free:true, install_count:0, avg_rating:0, rating_count:0, creator:'APEX Team'})) : [])];
  
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:4px">🏪 Agent Marketplace</h2>
      <p style="color:var(--text2);margin-bottom:20px">Discover, install, and deploy community agents</p>
      <div class="mp-category-bar">
        <button class="mp-cat-btn ${!mpCategory?'active':''}" onclick="mpCategory=null;renderMarketplace()">All</button>
        ${categories.map(c => `<button class="mp-cat-btn ${mpCategory===c.id?'active':''}" onclick="mpCategory='${c.id}';renderMarketplace()">${c.icon} ${c.name}</button>`).join('')}
      </div>
      <div class="mp-grid">
        ${allAgents.map(a => `
          <div class="mp-card" onclick="showMpAgent('${a.slug||a.agent_id}')">
            <div class="mp-icon">${a.icon||'🤖'}</div>
            <div class="mp-name">${a.name}</div>
            <div class="mp-desc">${a.description}</div>
            <div class="mp-meta">
              <span class="mp-price">${a.is_free||a.price_usd<=0?'FREE':'$'+a.price_usd}</span>
              ${a.avg_rating>0?`<span class="mp-rating">★ ${a.avg_rating.toFixed(1)}</span>`:''}
              <span class="mp-installs">📦 ${a.install_count||0}</span>
              <span>${a.creator||'community'}</span>
            </div>
          </div>`).join('')}
      </div>
    </div>`;
}

async function showMpAgent(slug) {
  const a = await api('/api/v1/marketplace/agents/' + slug);
  if (!a || a.error) return;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.onclick = e => { if(e.target===overlay) overlay.remove(); };
  overlay.innerHTML = `<div class="modal" style="position:relative">
    <div style="font-size:40px;margin-bottom:12px">${a.icon||'🤖'}</div>
    <div class="modal-title">${a.name}</div>
    <div style="color:var(--text2);margin-bottom:16px">${a.description}</div>
    <div style="display:flex;gap:16px;margin-bottom:16px;font-size:13px">
      <span class="mp-price" style="font-size:16px">${a.is_free?'FREE':'$'+a.price_usd}</span>
      <span>📦 ${a.install_count} installs</span>
      <span>🔄 ${a.total_runs} runs</span>
      ${a.avg_rating>0?`<span class="mp-rating">★ ${a.avg_rating} (${a.rating_count})</span>`:''}
    </div>
    ${a.long_description?`<div style="color:var(--text2);font-size:14px;line-height:1.6;margin-bottom:16px">${a.long_description}</div>`:''}
    ${a.tags&&a.tags.length?`<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px">${a.tags.map(t=>`<span class="mp-tag">${t}</span>`).join('')}</div>`:''}
    <div style="display:flex;gap:8px">
      <button class="btn btn-primary btn-lg" onclick="installMpAgent('${a.agent_id}',this)">Install Agent</button>
      <button class="btn btn-secondary" onclick="this.closest('.modal-overlay').remove()">Close</button>
    </div>
    <div id="mpInstallResult" style="margin-top:12px"></div>
  </div>`;
  document.body.appendChild(overlay);
}

async function installMpAgent(id, btn) {
  btn.innerHTML = '<div class="spinner"></div>';
  const r = await api('/api/v1/marketplace/agents/'+id+'/install', {method:'POST'});
  const el = document.getElementById('mpInstallResult');
  if (r.install_id) { el.innerHTML = `<div style="color:var(--green)">✅ Installed! Deploy from My Agents.</div>`; }
  else { el.innerHTML = `<div style="color:var(--red)">❌ ${r.detail||r.error||'Failed'}</div>`; }
  btn.innerHTML = 'Install Agent';
}

// ─── CREATE AGENT ────────────────────────────────
function renderCreateAgent() {
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">🛠️ Create Custom Agent</h2>
      <div class="grid-2">
        <div class="card">
          <div class="deploy-form">
            <div class="form-group"><label class="form-label">Agent Name</label><input class="form-input" id="caName" placeholder="e.g. Alpha Scanner"></div>
            <div class="form-group"><label class="form-label">Icon</label><input class="form-input" id="caIcon" value="🤖" style="width:60px;text-align:center;font-size:24px"></div>
            <div class="form-group"><label class="form-label">Short Description</label><input class="form-input" id="caDesc" placeholder="One line about what it does"></div>
            <div class="form-group"><label class="form-label">Category</label>
              <select class="form-select" id="caCat"><option>Crypto & DeFi</option><option>Coding & Dev</option><option>Writing & Content</option><option>Data & Research</option><option>Business & Strategy</option><option>Productivity</option></select>
            </div>
            <div class="form-group"><label class="form-label">System Prompt</label><textarea class="form-textarea" id="caPrompt" style="min-height:180px" placeholder="You are an expert at..."></textarea></div>
            <div class="form-group"><label class="form-label">Price (USD) — 0 = free</label><input class="form-input" id="caPrice" type="number" value="0" min="0" step="0.99"></div>
            <div class="form-group"><label class="form-label">Creator Name</label><input class="form-input" id="caCreator" placeholder="Your name or handle"></div>
            <button class="btn btn-primary btn-lg" onclick="createMpAgent()">Create Agent</button>
            <div id="caResult" style="margin-top:12px"></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title" style="margin-bottom:12px">Tips</div>
          <div style="color:var(--text2);font-size:14px;line-height:1.8">
            <p>📝 <strong>System prompt</strong> is the soul of your agent. Be specific about expertise, output format, and behavior.</p><br>
            <p>💰 <strong>Pricing</strong>: Free agents get more installs. Paid agents earn you 80% of each sale.</p><br>
            <p>🏷️ <strong>After creating</strong>, publish it to make it visible in the marketplace.</p>
          </div>
        </div>
      </div>
    </div>`;
}

async function createMpAgent() {
  const data = {
    name: document.getElementById('caName').value,
    description: document.getElementById('caDesc').value,
    system_prompt: document.getElementById('caPrompt').value,
    category: document.getElementById('caCat').value,
    icon: document.getElementById('caIcon').value,
    price_usd: parseFloat(document.getElementById('caPrice').value) || 0,
    creator_name: document.getElementById('caCreator').value || 'anonymous',
  };
  const r = await api('/api/v1/marketplace/agents', {method:'POST', body:JSON.stringify(data)});
  const el = document.getElementById('caResult');
  if (r.agent_id) {
    el.innerHTML = `<div style="background:var(--greenbg);border:1px solid var(--green);border-radius:8px;padding:12px">✅ Created! <strong>${r.slug}</strong><br><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="publishAgent('${r.agent_id}',this)">Publish to Marketplace</button></div>`;
  } else {
    el.innerHTML = `<div style="color:var(--red)">❌ ${r.detail||r.error||'Failed'}</div>`;
  }
}

async function publishAgent(id, btn) {
  btn.innerHTML = '<div class="spinner"></div>';
  await api('/api/v1/marketplace/agents/'+id+'/publish', {method:'POST'});
  btn.innerHTML = '✅ Published!';
  btn.disabled = true;
}

// ─── MY STORE ────────────────────────────────────
async function renderMyStore() {
  const [agents, earnings] = await Promise.all([api('/api/v1/marketplace/my-agents'), api('/api/v1/marketplace/earnings')]);
  const myAgents = agents.agents || [];
  const e = earnings || {};
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">💰 My Store</h2>
      <div class="grid-3" style="margin-bottom:24px">
        <div class="stat"><div class="stat-value">$${(e.total_earned||0).toFixed(2)}</div><div class="stat-label">Total Earned</div></div>
        <div class="stat"><div class="stat-value">${e.total_sales||0}</div><div class="stat-label">Total Sales</div></div>
        <div class="stat"><div class="stat-value">${myAgents.length}</div><div class="stat-label">My Agents</div></div>
      </div>
      <div class="card">${myAgents.length ? myAgents.map(a => `
        <div class="agent-row">
          <span style="font-size:20px">${a.icon||'🤖'}</span>
          <div class="agent-name">${a.name}</div>
          <span style="font-size:12px;color:var(--text2)">📦${a.install_count} ★${a.avg_rating||0}</span>
          <span style="font-size:12px;color:${a.published?'var(--green)':'var(--text2)'}">${a.published?'Published':'Draft'}</span>
          ${!a.published?`<button class="btn btn-primary btn-sm" onclick="publishAgent('${a.agent_id}',this)">Publish</button>`:''}
        </div>`).join('') : '<div class="empty-state"><div class="empty-state-icon">🛠️</div><div class="empty-state-text">No agents yet</div><button class="btn btn-primary" onclick="navigate(\'create-agent\')">Create Agent</button></div>'}</div>
    </div>`;
}

// ─── WORKFLOWS ───────────────────────────────────
async function renderWorkflows() {
  const [wfs, templates] = await Promise.all([api('/api/v1/workflows'), api('/api/v1/workflows/templates')]);
  const workflows = wfs.workflows || [];
  const tmpls = templates.templates || {};
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">⚙️ Workflows</h2>
      <div style="margin-bottom:20px"><h3 style="font-size:16px;margin-bottom:12px;color:var(--text2)">Quick Start Templates</h3>
        <div class="grid-3">${Object.entries(tmpls).map(([id,t])=>`
          <div class="card" style="cursor:pointer" onclick="createWorkflow('${id}')">
            <div class="card-title" style="font-size:14px">${t.name}</div>
            <div class="card-subtitle">${t.description}</div>
            <div style="margin-top:8px;font-size:11px;color:var(--green)">Trigger: ${t.trigger_type}</div>
          </div>`).join('')}</div>
      </div>
      <h3 style="font-size:16px;margin-bottom:12px">Active Workflows</h3>
      <div class="card">${workflows.length ? workflows.map(w => `
        <div class="agent-row">
          <div class="agent-status ${w.enabled?'running':'failed'}"></div>
          <div class="agent-name">${w.name}</div>
          <div style="font-size:12px;color:var(--text2)">${w.trigger_type} → ${w.fire_count} fires</div>
          <button class="btn btn-sm btn-secondary" onclick="toggleWorkflow('${w.workflow_id}')">Toggle</button>
        </div>`).join('') : '<div style="color:var(--text2);padding:16px;text-align:center">No workflows. Use a template above to get started.</div>'}</div>
    </div>`;
}

async function createWorkflow(templateId) {
  const r = await api('/api/v1/workflows', {method:'POST', body:JSON.stringify({name:'',trigger_type:'',actions:[],template_id:templateId})});
  if (r.workflow_id) renderWorkflows();
}

async function toggleWorkflow(id) {
  await api('/api/v1/workflows/'+id+'/toggle', {method:'POST'});
  renderWorkflows();
}

// ─── DAEMONS ─────────────────────────────────────
async function renderDaemons() {
  const r = await api('/api/v1/daemons');
  const daemons = r.daemons || [];
  const presets = r.presets || {};
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">👁️ Daemons — 24/7 Monitors</h2>
      <div class="grid-3" style="margin-bottom:20px">${Object.entries(presets).map(([id,p])=>`
        <div class="card" style="cursor:pointer" onclick="startDaemon('${id}')">
          <div class="card-title" style="font-size:14px">${p.name}</div>
          <div class="card-subtitle">${(p.task_description||'').slice(0,80)}</div>
          <div style="margin-top:8px;font-size:11px;color:var(--text2)">Every ${p.interval_seconds}s</div>
        </div>`).join('')}</div>
      <h3 style="font-size:16px;margin-bottom:12px">Running Daemons</h3>
      <div class="card">${daemons.length ? daemons.map(d => `
        <div class="agent-row">
          <div class="agent-status ${d.status==='running'?'running':'failed'}"></div>
          <div class="agent-name">${d.agent_name}</div>
          <div style="font-size:12px;color:var(--text2)">${d.cycles} cycles</div>
          <button class="btn btn-danger btn-sm" onclick="stopDaemon('${d.daemon_id}')">Stop</button>
        </div>`).join('') : '<div style="color:var(--text2);padding:16px;text-align:center">No daemons running. Click a preset above to start.</div>'}</div>
    </div>`;
}

async function startDaemon(id) { await api('/api/v1/daemons/start', {method:'POST', body:JSON.stringify({preset_id:id})}); renderDaemons(); }
async function stopDaemon(id) { await api('/api/v1/daemons/'+id+'/stop', {method:'POST'}); renderDaemons(); }

// ─── MODELS ──────────────────────────────────────
async function renderModels() {
  const r = await api('/api/v1/models');
  const providers = r.providers || [];
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">🧠 AI Models — ${r.available_count||1} Providers Active</h2>
      <div style="display:flex;flex-direction:column;gap:16px">${providers.map(p => `
        <div class="card">
          <div class="card-header"><div><div class="card-title">${p.name} ${p.available?'🟢':'🔴'}</div><div class="card-subtitle">${p.available?'Connected':'Add '+p.provider.toUpperCase()+'_API_KEY to enable'}</div></div></div>
          ${p.available?`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px">${p.models.map(m=>`<div style="background:var(--surface2);padding:10px;border-radius:8px;font-size:13px"><strong>${m.name}</strong>${m.vision?' 👁️':''}<br><span style="color:var(--text2);font-size:11px">${m.context_window.toLocaleString()} ctx · $${m.cost_per_1m_input}/M in</span></div>`).join('')}</div>`:''}
        </div>`).join('')}</div>
    </div>`;
}

// ─── CHANNELS ────────────────────────────────────
async function renderChannels() {
  const r = await api('/api/v1/channels');
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">💬 Messaging Channels</h2>
      <div class="grid-3">${Object.entries(r||{}).map(([name,info])=>`
        <div class="card"><div style="font-size:32px;margin-bottom:8px">${name==='telegram'?'📱':name==='discord'?'🎮':'💼'}</div>
        <div class="card-title">${name.charAt(0).toUpperCase()+name.slice(1)}</div>
        <div style="margin-top:8px;font-size:13px;color:${info.enabled?'var(--green)':'var(--text2)'}">${info.enabled?'✅ Connected':'❌ Not configured'}</div>
        ${!info.enabled?`<div style="margin-top:8px;font-size:12px;color:var(--text2)">Add ${name.toUpperCase()}_BOT_TOKEN to enable</div>`:''}</div>`).join('')}</div>
    </div>`;
}

// ─── SCHEDULES ───────────────────────────────────
async function renderSchedules() {
  const r = await api('/api/v1/schedules');
  const schedules = r.schedules || [];
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">🕐 Schedules</h2>
      <div class="card">${schedules.length ? schedules.map(s => `
        <div class="agent-row">
          <div class="agent-status ${s.enabled?'running':'failed'}"></div>
          <div class="agent-name">${s.agent_type}</div>
          <div style="font-size:12px;color:var(--text2);font-family:'Space Mono',monospace">${s.cron_expression}</div>
          <div style="font-size:12px;color:var(--text2)">Next: ${s.next_run||'—'}</div>
        </div>`).join('') : '<div class="empty-state"><div class="empty-state-icon">🕐</div><div class="empty-state-text">No schedules configured</div></div>'}</div>
    </div>`;
}

// ─── SETTINGS ────────────────────────────────────
async function renderSettings() {
  const h = await api('/api/v1/health');
  document.getElementById('mainContent').innerHTML = `
    <div class="fade-in">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">⚙️ Settings</h2>
      <div class="card" style="margin-bottom:16px">
        <div class="card-title" style="margin-bottom:12px">System Info</div>
        <div style="font-family:'Space Mono',monospace;font-size:13px;color:var(--text2);line-height:2">
          Version: ${h.version||'?'}<br>
          Database: ${h.database||'?'}<br>
          Auth: ${h.auth||'?'}<br>
          API URL: ${BASE_URL}<br>
        </div>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:12px">API Key</div>
        <div class="form-group">
          <input class="form-input" id="settingsKey" value="${API_KEY}" style="font-family:'Space Mono',monospace;font-size:12px">
          <button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="API_KEY=document.getElementById('settingsKey').value;localStorage.setItem('apex_api_key',API_KEY)">Save</button>
        </div>
      </div>
    </div>`;
}

// ─── SSE LIVE EVENTS ─────────────────────────────
function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(BASE_URL + '/api/v1/events/stream');
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.event_type) {
        liveEvents.push(data);
        if (liveEvents.length > 100) liveEvents.shift();
        if (currentPage === 'feed') renderFeed();
        if (currentPage === 'overview') loadOverviewEvents();
      }
    } catch(err) {}
  };
  eventSource.onerror = () => {
    document.getElementById('statusDot').style.background = 'var(--red)';
    document.getElementById('statusText').textContent = 'Disconnected';
    setTimeout(connectSSE, 5000);
  };
  eventSource.onopen = () => {
    document.getElementById('statusDot').style.background = 'var(--green)';
    document.getElementById('statusText').textContent = 'Connected';
  };
}

// ─── INIT ────────────────────────────────────────
document.getElementById('apiKeyInput').value = API_KEY;
connectSSE();
navigate('overview');
</script>
</body>
</html>
"""


# ─── ENTRYPOINT ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
