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
import time
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
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STARTER_PRICE = os.getenv("STRIPE_STARTER_PRICE", "")
STRIPE_PRO_PRICE = os.getenv("STRIPE_PRO_PRICE", "")
STRIPE_ENTERPRISE_PRICE = os.getenv("STRIPE_ENTERPRISE_PRICE", "")
JWT_SECRET = os.getenv("JWT_SECRET", "apex-swarm-jwt-secret-change-in-prod")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "https://apex-swarm-v2-production.up.railway.app")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STARTER_PRICE = os.getenv("STRIPE_STARTER_PRICE", "")
STRIPE_PRO_PRICE = os.getenv("STRIPE_PRO_PRICE", "")
STRIPE_ENTERPRISE_PRICE = os.getenv("STRIPE_ENTERPRISE_PRICE", "")
JWT_SECRET = os.getenv("JWT_SECRET", "apex-swarm-jwt-secret-change-in-prod")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "https://apex-swarm-v2-production.up.railway.app")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_DEFAULT_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#ai-workforce")
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

# Agent-to-Agent Protocol
A2A_AVAILABLE = False
a2a_engine = None
try:
    from a2a_protocol import A2AEngine, discover_agent as a2a_discover
    A2A_AVAILABLE = True
    logger.info("✅ a2a_protocol loaded — agents can hire and delegate to other agents")
except ImportError:
    logger.warning("⚠️ a2a_protocol not found — no agent-to-agent delegation")

# Autonomous Goal System
GOALS_AVAILABLE = False
goal_engine = None
try:
    from autonomous_goals import GoalEngine, ROLES, EMAIL_PERMISSIONS, COMPETITOR_DAEMON_CONFIG, get_tools_for_role, check_email_permission
    GOALS_AVAILABLE = True
    logger.info("✅ autonomous_goals loaded — goal system, role permissions, org charts")
except ImportError:
    ROLES = {}
    COMPETITOR_DAEMON_CONFIG = {}
    logger.warning("⚠️ autonomous_goals not found — no goal system")

# Enterprise hardening
ENTERPRISE = False
try:
    from enterprise import (
        retry_with_backoff, RetryConfig, CircuitBreaker, circuit_breakers,
        ConversationStore, sanitize_input, sanitize_output, AuditLog,
        MetricsCollector, metrics_collector, LatencyTracker,
        get_api_docs,
    )
    ENTERPRISE = True
    logger.info("✅ enterprise loaded — reliability, security, observability, docs")
except ImportError:
    metrics_collector = None
    logger.warning("⚠️ enterprise not found — no hardening")

conversation_store = None
audit_log = None

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

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    tier TEXT DEFAULT 'free',
                    stripe_customer_id TEXT DEFAULT '',
                    stripe_subscription_id TEXT DEFAULT '',
                    api_key TEXT UNIQUE NOT NULL,
                    org_id TEXT DEFAULT '',
                    role TEXT DEFAULT 'owner',
                    google_id TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    user_email TEXT,
                    org_id TEXT,
                    action TEXT NOT NULL,
                    resource TEXT,
                    detail TEXT,
                    ip TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orgs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'enterprise',
                    owner_email TEXT NOT NULL,
                    slack_webhook TEXT DEFAULT '',
                    slack_channel TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS org_members (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    api_key TEXT UNIQUE NOT NULL,
                    invited_by TEXT,
                    joined_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS org_invites (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    token TEXT UNIQUE NOT NULL,
                    created_by TEXT NOT NULL,
                    used INTEGER DEFAULT 0,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    tier TEXT DEFAULT 'free',
                    stripe_customer_id TEXT DEFAULT '',
                    stripe_subscription_id TEXT DEFAULT '',
                    api_key TEXT UNIQUE NOT NULL,
                    org_id TEXT DEFAULT '',
                    role TEXT DEFAULT 'owner',
                    google_id TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    user_email TEXT,
                    org_id TEXT,
                    action TEXT NOT NULL,
                    resource TEXT,
                    detail TEXT,
                    ip TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orgs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'enterprise',
                    owner_email TEXT NOT NULL,
                    slack_webhook TEXT DEFAULT '',
                    slack_channel TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS org_members (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    api_key TEXT UNIQUE NOT NULL,
                    invited_by TEXT,
                    joined_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS org_invites (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    token TEXT UNIQUE NOT NULL,
                    created_by TEXT NOT NULL,
                    used INTEGER DEFAULT 0,
                    expires_at TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS orgs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'enterprise',
                    owner_email TEXT NOT NULL,
                    slack_webhook TEXT DEFAULT '',
                    slack_channel TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS org_members (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    api_key TEXT UNIQUE NOT NULL,
                    invited_by TEXT,
                    joined_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS org_invites (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    token TEXT UNIQUE NOT NULL,
                    created_by TEXT NOT NULL,
                    used INTEGER DEFAULT 0,
                    expires_at TEXT NOT NULL,
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

            # Migration: add missing columns if they don't exist
            migration_columns = [
                ("knowledge", "pattern", "TEXT DEFAULT ''"),
                ("knowledge", "source_url", "TEXT DEFAULT ''"),
                ("knowledge", "tags", "TEXT DEFAULT '[]'"),
                ("knowledge", "success_count", "INTEGER DEFAULT 0"),
                ("knowledge", "fail_count", "INTEGER DEFAULT 0"),
                ("knowledge", "relevance_score", "REAL DEFAULT 0.0"),
                ("knowledge", "embedding", "TEXT DEFAULT ''"),
                ("knowledge", "metadata", "TEXT DEFAULT '{}'"),
                ("knowledge", "expires_at", "TEXT DEFAULT ''"),
                ("knowledge", "category", "TEXT DEFAULT 'general'"),
                ("knowledge", "source_agent", "TEXT DEFAULT ''"),
                ("knowledge", "version", "INTEGER DEFAULT 1"),
                ("audit_log", "flagged", "BOOLEAN DEFAULT FALSE"),
            ]
            for table, col, col_type in migration_columns:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    conn.commit()
                    logger.info(f"✅ Migration: added {table}.{col}")
                except Exception:
                    try:
                        conn.cursor().execute("ROLLBACK")
                    except Exception:
                        pass
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

    # Shared LLM call function for A2A and Goals
    async def _shared_llm_call(system_prompt: str, message: str, model: str = None) -> str:
        """LLM call for decomposition and aggregation."""
        if MULTI_MODEL and model_router:
            result = await model_router.call(
                model_id=model or CLAUDE_MODEL,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": message}],
                max_tokens=4096,
            )
            return result.get("text", "")
        else:
            import httpx
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": CLAUDE_MODEL, "max_tokens": 4096, "system": system_prompt, "messages": [{"role": "user", "content": message}]})
            if resp.status_code == 200:
                return resp.json().get("content", [{}])[0].get("text", "")
            return ""

    # Initialize A2A engine
    if A2A_AVAILABLE:
        global a2a_engine
        a2a_engine = A2AEngine(AGENTS, execute_task, _shared_llm_call)
        a2a_engine.set_db(get_db, USER_KEY_COL)
        logger.info("✅ A2A engine initialized — agent delegation active")

    # Initialize Goal Engine
    if GOALS_AVAILABLE:
        global goal_engine
        goal_engine = GoalEngine(AGENTS, execute_task, _shared_llm_call)
        goal_engine.set_db(get_db, USER_KEY_COL)
        logger.info("✅ Goal engine initialized — autonomous goals active")

    # Add competitor tracking daemon preset
    if GOALS_AVAILABLE and MISSION_CONTROL and COMPETITOR_DAEMON_CONFIG:
        DAEMON_PRESETS["competitor-intel"] = COMPETITOR_DAEMON_CONFIG
        logger.info("✅ Competitor tracking daemon preset added")

    # Initialize enterprise components
    if ENTERPRISE:
        global conversation_store, audit_log
        conversation_store = ConversationStore(get_db, db_execute, db_fetchall, USER_KEY_COL)
        audit_log = AuditLog(get_db, db_execute, db_fetchall)
        conn = get_db()
        try:
            conversation_store.init_tables(conn)
            audit_log.init_tables(conn)
            logger.info("✅ Enterprise tables initialized (conversations, audit_log)")
        except Exception as e:
            logger.error(f"Enterprise init failed: {e}")
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


async def send_slack_message(text: str, webhook_url: str = None, channel: str = None, blocks: list = None) -> bool:
    """Send a message to Slack via webhook."""
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return False
    payload = {"text": text}
    if channel:
        payload["channel"] = channel
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Slack send failed: {e}")
        return False

async def send_slack_agent_result(agent_type: str, agent_name: str, task: str, result: str,
                                   webhook_url: str = None, channel: str = None):
    """Send formatted agent result to Slack."""
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    preview = result[:500] + ("..." if len(result) > 500 else "")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Agent Complete: " + agent_name}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": "*Agent:* " + agent_name},
            {"type": "mrkdwn", "text": "*Type:* " + agent_type}
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Task:* " + task[:200]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Result:* " + preview}},
        {"type": "divider"}
    ]
    await send_slack_message(f"⚡ {agent_name} completed", webhook_url=url, channel=channel, blocks=blocks)

async def send_slack_daemon_alert(agent_name: str, condition: str, result: str,
                                   webhook_url: str = None, channel: str = None):
    """Send daemon alert to Slack."""
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    preview = result[:600] + ("..." if len(result) > 600 else "")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 ALERT: {agent_name}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Triggered condition:* `{condition}`"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Report:* " + preview}},
        {"type": "divider"}
    ]
    await send_slack_message(f"🚨 Alert from {agent_name}", webhook_url=url, channel=channel, blocks=blocks)


async def send_slack_message(text, webhook_url=None, channel=None, blocks=None):
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return False
    payload = {"text": text}
    if channel:
        payload["channel"] = channel
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error("Slack send failed: " + str(e))
        return False

async def send_slack_agent_result(agent_type, agent_name, task, result, webhook_url=None, channel=None):
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    preview = (result or "")[:500]
    await send_slack_message(
        "Agent " + agent_name + " completed: " + preview,
        webhook_url=url, channel=channel
    )

async def send_slack_daemon_alert(agent_name, condition, result, webhook_url=None, channel=None):
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    preview = (result or "")[:600]
    await send_slack_message(
        "ALERT from " + agent_name + " [" + condition + "]: " + preview,
        webhook_url=url, channel=channel
    )


async def send_slack_message(text, webhook_url=None, channel=None, blocks=None):
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return False
    payload = {"text": text}
    if channel:
        payload["channel"] = channel
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error("Slack send failed: " + str(e))
        return False

async def send_slack_agent_result(agent_type, agent_name, task, result, webhook_url=None, channel=None):
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    preview = (result or "")[:500]
    await send_slack_message(
        "Agent " + agent_name + " completed: " + preview,
        webhook_url=url, channel=channel
    )

async def send_slack_daemon_alert(agent_name, condition, result, webhook_url=None, channel=None):
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    preview = (result or "")[:600]
    await send_slack_message(
        "ALERT from " + agent_name + " [" + condition + "]: " + preview,
        webhook_url=url, channel=channel
    )


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


# ─── ENTERPRISE ORG AUTH ─────────────────────────────────

def get_member_by_key(api_key: str):
    """Look up org member by their API key."""
    conn = get_db()
    try:
        row = db_fetchone(conn,
            "SELECT m.id, m.org_id, m.email, m.role, o.name as org_name, o.tier, o.slack_webhook, o.slack_channel "
            "FROM org_members m JOIN orgs o ON m.org_id = o.id WHERE m.api_key = ?",
            (api_key,)
        )
        if row:
            return {"member_id": row[0], "org_id": row[1], "email": row[2],
                    "role": row[3], "org_name": row[4], "tier": row[5],
                    "slack_webhook": row[6], "slack_channel": row[7]}
        return None
    finally:
        conn.close()

def get_org_by_id(org_id: str):
    conn = get_db()
    try:
        row = db_fetchone(conn, "SELECT id, name, slug, tier, owner_email, slack_webhook, slack_channel FROM orgs WHERE id = ?", (org_id,))
        if row:
            return {"id": row[0], "name": row[1], "slug": row[2], "tier": row[3],
                    "owner_email": row[4], "slack_webhook": row[5], "slack_channel": row[6]}
        return None
    finally:
        conn.close()

async def get_validated_org_user(x_api_key: str = Header(None), authorization: str = Header(None)) -> dict:
    """Validate API key — checks org members first, falls back to Gumroad license."""
    key = x_api_key or ""
    if not key and authorization:
        key = authorization.replace("Bearer ", "")
    if not key:
        raise HTTPException(status_code=401, detail="API key required.")
    if ADMIN_API_KEY and key == ADMIN_API_KEY:
        return {"api_key": key, "tier": "admin", "email": "admin", "org_id": None, "role": "admin"}
    # Check org member first
    member = get_member_by_key(key)
    if member:
        return {"api_key": key, "tier": member["tier"], "email": member["email"],
                "org_id": member["org_id"], "role": member["role"],
                "org_name": member["org_name"], "slack_webhook": member["slack_webhook"],
                "slack_channel": member["slack_channel"]}
    # Fall back to Gumroad license
    result = await get_or_validate_license(key)
    if not result.get("valid"):
        raise HTTPException(status_code=403, detail=result.get("error", "Invalid license key"))
    return {"api_key": key, "tier": result.get("tier", "starter"), "email": result.get("email", ""),
            "org_id": None, "role": "owner", "slack_webhook": "", "slack_channel": ""}


# ─── ORG MANAGEMENT ENDPOINTS ────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str
    slug: str
    owner_email: str
    slack_webhook: Optional[str] = ""
    slack_channel: Optional[str] = ""

class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"

class AcceptInviteRequest(BaseModel):
    token: str
    email: str

class UpdateOrgRequest(BaseModel):
    slack_webhook: Optional[str] = None
    slack_channel: Optional[str] = None
    name: Optional[str] = None


# ─── USER + ORG AUTH ─────────────────────────────────────

import hashlib as _hl, hmac as _hm, base64 as _b64, json as _json

def hash_password(pw):
    salt = os.urandom(16)
    dk = _hl.pbkdf2_hmac("sha256", pw.encode(), salt, 100000)
    return _b64.b64encode(salt + dk).decode()

def verify_password(pw, stored):
    try:
        raw = _b64.b64decode(stored.encode())
        salt, dk = raw[:16], raw[16:]
        check = _hl.pbkdf2_hmac("sha256", pw.encode(), salt, 100000)
        return _hm.compare_digest(dk, check)
    except Exception:
        return False

def make_token(user_id):
    p = _json.dumps({"u": user_id, "t": datetime.now(timezone.utc).isoformat()})
    s = _hm.new(JWT_SECRET.encode(), p.encode(), _hl.sha256).hexdigest()
    return _b64.urlsafe_b64encode((p + "|" + s).encode()).decode()

def get_user_by_token(token):
    try:
        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row = db_fetchone(conn,
            "SELECT s.user_id,u.email,u.tier,u.api_key,u.org_id,u.role FROM sessions s "
            "JOIN users u ON s.user_id=u.id WHERE s.token=? AND s.expires_at>?",
            (token, now))
        conn.close()
        if row:
            return {"user_id":row[0],"email":row[1],"tier":row[2],"api_key":row[3],"org_id":row[4],"role":row[5]}
        return None
    except Exception:
        return None

def get_member_by_key(api_key):
    conn = get_db()
    try:
        row = db_fetchone(conn,
            "SELECT m.id,m.org_id,m.email,m.role,o.name,o.tier,o.slack_webhook,o.slack_channel "
            "FROM org_members m JOIN orgs o ON m.org_id=o.id WHERE m.api_key=?",
            (api_key,))
        if row:
            return {"member_id":row[0],"org_id":row[1],"email":row[2],"role":row[3],
                    "org_name":row[4],"tier":row[5],"slack_webhook":row[6],"slack_channel":row[7]}
        return None
    finally:
        conn.close()

def log_audit(user_email, action, resource="", detail="", user_id="", org_id="", ip=""):
    try:
        conn = get_db()
        db_execute(conn, "INSERT INTO audit_log (id,user_id,user_email,org_id,action,resource,detail,ip,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()),user_id,user_email,org_id,action,resource,str(detail)[:500],ip,datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Audit: " + str(e))


# ─── USER + ORG AUTH ─────────────────────────────────────

import hashlib as _hl, hmac as _hm, base64 as _b64, json as _json

def hash_password(pw):
    salt = os.urandom(16)
    dk = _hl.pbkdf2_hmac("sha256", pw.encode(), salt, 100000)
    return _b64.b64encode(salt + dk).decode()

def verify_password(pw, stored):
    try:
        raw = _b64.b64decode(stored.encode())
        salt, dk = raw[:16], raw[16:]
        check = _hl.pbkdf2_hmac("sha256", pw.encode(), salt, 100000)
        return _hm.compare_digest(dk, check)
    except Exception:
        return False

def make_token(user_id):
    p = _json.dumps({"u": user_id, "t": datetime.now(timezone.utc).isoformat()})
    s = _hm.new(JWT_SECRET.encode(), p.encode(), _hl.sha256).hexdigest()
    return _b64.urlsafe_b64encode((p + "|" + s).encode()).decode()

def get_user_by_token(token):
    try:
        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row = db_fetchone(conn,
            "SELECT s.user_id,u.email,u.tier,u.api_key,u.org_id,u.role FROM sessions s "
            "JOIN users u ON s.user_id=u.id WHERE s.token=? AND s.expires_at>?",
            (token, now))
        conn.close()
        if row:
            return {"user_id":row[0],"email":row[1],"tier":row[2],"api_key":row[3],"org_id":row[4],"role":row[5]}
        return None
    except Exception:
        return None

def get_member_by_key(api_key):
    conn = get_db()
    try:
        row = db_fetchone(conn,
            "SELECT m.id,m.org_id,m.email,m.role,o.name,o.tier,o.slack_webhook,o.slack_channel "
            "FROM org_members m JOIN orgs o ON m.org_id=o.id WHERE m.api_key=?",
            (api_key,))
        if row:
            return {"member_id":row[0],"org_id":row[1],"email":row[2],"role":row[3],
                    "org_name":row[4],"tier":row[5],"slack_webhook":row[6],"slack_channel":row[7]}
        return None
    finally:
        conn.close()

def log_audit(user_email, action, resource="", detail="", user_id="", org_id="", ip=""):
    try:
        conn = get_db()
        db_execute(conn, "INSERT INTO audit_log (id,user_id,user_email,org_id,action,resource,detail,ip,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()),user_id,user_email,org_id,action,resource,str(detail)[:500],ip,datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Audit: " + str(e))


# ─── KNOWLEDGE RETRIEVAL ─────────────────────────────────

def get_knowledge_for_agent(user_api_key: str, agent_type: str, task: str = "") -> str:
    """Get relevant knowledge entries for context injection."""
    try:
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
    except Exception as e:
        logger.warning(f"Knowledge retrieval failed (non-fatal): {e}")
        return ""


# ─── CORE EXECUTION ──────────────────────────────────────

async def execute_task(agent_id: str, agent_type: str, task_description: str, user_api_key: str = "system", model: str = None, image_data: str = None, image_media_type: str = "image/jpeg"):
    """Execute a single agent task. Enterprise-hardened with retries, sanitization, metrics."""
    start_time = time.time() if ENTERPRISE else 0

    # ── SECURITY: Input sanitization ──
    if ENTERPRISE:
        scan = sanitize_input(task_description)
        if scan["blocked"]:
            logger.warning(f"🛡️ Blocked input from {user_api_key[:8]}: {scan['flags']}")
            if audit_log:
                audit_log.log("input.blocked", user_api_key, agent_type,
                              {"flags": scan["flags"], "agent_id": agent_id}, risk_score=scan["risk_score"])
            conn = get_db()
            try:
                conn.execute("UPDATE agents SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                    ("Request blocked by security filter.", datetime.now(timezone.utc).isoformat(), agent_id))
                conn.commit()
            finally:
                conn.close()
            return
        if scan["flags"] and audit_log:
            audit_log.log("input.flagged", user_api_key, agent_type,
                          {"flags": scan["flags"], "agent_id": agent_id}, risk_score=scan["risk_score"])

    # ── METRICS: Track deployment ──
    if ENTERPRISE and metrics_collector:
        metrics_collector.record("agent.deployed", 1, {"type": agent_type})

    # ── PERSISTENCE: Inject conversation context ──
    if ENTERPRISE and conversation_store:
        try:
            context = conversation_store.get_context(user_api_key, agent_type)
            if context:
                task_description = task_description + "\n\n" + context
        except Exception:
            pass

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
        # ── SECURITY: Sanitize output ──
        if ENTERPRISE and result:
            result = sanitize_output(result)

        conn = get_db()
        try:
            conn.execute(
                "UPDATE agents SET status = 'completed', result = ?, completed_at = ? WHERE id = ?",
                (result, datetime.now(timezone.utc).isoformat(), agent_id),
            )
            conn.commit()
        finally:
            conn.close()

        # ── PERSISTENCE: Save conversation turn ──
        if ENTERPRISE and conversation_store and result:
            try:
                conversation_store.save_turn(user_api_key, agent_type, task_description[:500], result)
            except Exception:
                pass

        # ── METRICS: Record success + latency ──
        if ENTERPRISE and metrics_collector:
            duration = time.time() - start_time
            metrics_collector.record("agent.completed", 1, {"type": agent_type})
            metrics_collector.histogram("agent.latency", duration, {"type": agent_type})

        # ── AUDIT: Log completion ──
        if ENTERPRISE and audit_log:
            audit_log.log("agent.completed", user_api_key, agent_type,
                          {"agent_id": agent_id, "result_length": len(result) if result else 0})

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

        # ── DAEMON ALERT: Check if result contains alert keywords ──
        if MISSION_CONTROL and user_api_key and user_api_key.startswith("daemon:"):
            try:
                # Get alert conditions for this daemon from DB
                conn = get_db()
                try:
                    row = conn.execute(
                        f"SELECT alert_conditions FROM daemon_configs WHERE id = ?",
                        (agent_id,)
                    ).fetchone()
                    alert_conds = json.loads(row[0]) if row and row[0] else []
                finally:
                    conn.close()

                result_lower = (result or "").lower()
                triggered = [kw for kw in alert_conds if kw.lower() in result_lower]
                # Also check for explicit ALERT: prefix from agent
                has_alert_prefix = "alert:" in result_lower

                if triggered or has_alert_prefix:
                    await event_bus.emit(Event(
                        event_type=EventType.DAEMON_ALERT,
                        agent_id=agent_id,
                        agent_type=agent_type,
                        agent_name=agent.get("name", agent_type),
                        message=result[:800] if result else "",
                        data={"triggered_keywords": triggered},
                    ))
                    logger.info(f"🚨 Daemon alert fired for {agent_id[:8]}: {triggered}")
                    # Send to Slack
                    if SLACK_WEBHOOK_URL:
                        asyncio.create_task(send_slack_daemon_alert(
                            agent_name=agent.get("name", agent_type),
                            condition=", ".join(triggered) if triggered else "ALERT",
                            result=result or "",
                        ))
            except Exception as e:
                logger.error(f"Daemon alert check failed: {e}")

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

        # ── SLACK OUTPUT: Send result to org Slack if configured ──
        if result and SLACK_WEBHOOK_URL:
            try:
                # Check if this is a daemon run (skip — daemon alerts handled separately)
                if not (user_api_key and user_api_key.startswith("daemon:")):
                    asyncio.create_task(send_slack_agent_result(
                        agent_type=agent_type,
                        agent_name=agent.get("name", agent_type),
                        task=task_description,
                        result=result,
                    ))
            except Exception as e:
                logger.error(f"Slack output failed: {e}")

        # ── SLACK OUTPUT: Check org member's Slack config ──
        if result and user_api_key and not user_api_key.startswith("daemon:"):
            try:
                member = get_member_by_key(user_api_key)
                if member and member.get("slack_webhook"):
                    asyncio.create_task(send_slack_agent_result(
                        agent_type=agent_type,
                        agent_name=agent.get("name", agent_type),
                        task=task_description,
                        result=result,
                        webhook_url=member["slack_webhook"],
                        channel=member["slack_channel"],
                    ))
            except Exception as e:
                logger.error(f"Org Slack output failed: {e}")

        return result

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Task execution failed ({agent_id}): {e}\n{tb}")
        conn = get_db()
        try:
            conn.execute(
                "UPDATE agents SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                (f"Error: {str(e)}\n\nTraceback:\n{tb[:1000]}", datetime.now(timezone.utc).isoformat(), agent_id),
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
    # Tag with daemon: prefix so alert logic can identify daemon runs
    tagged_key = f"daemon:{user_api_key}" if not user_api_key.startswith("daemon:") else user_api_key
    return await execute_task(agent_id, agent_type, prompt, tagged_key)


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
        _tg_chat_ids = set()
        if TELEGRAM_CHAT_ID:
            try:
                _tg_chat_ids.add(int(TELEGRAM_CHAT_ID))
                logger.info(f"📡 Telegram chat_id loaded: {TELEGRAM_CHAT_ID}")
            except ValueError:
                logger.warning(f"⚠️ Invalid TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")
        event_bus.set_telegram(send_fn=send_telegram, chat_ids=_tg_chat_ids if _tg_chat_ids else None, verbosity="important")
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

@app.post("/api/v1/orgs")
async def create_org(req: CreateOrgRequest, api_key: str = Depends(get_api_key)):
    """Create a new organization."""
    import re
    slug = re.sub(r'[^a-z0-9-]', '-', req.slug.lower()).strip('-')
    org_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    member_key = f"ak-{str(uuid.uuid4()).replace('-', '')[:32]}"
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn, "INSERT INTO orgs (id, name, slug, tier, owner_email, slack_webhook, slack_channel, created_at) VALUES (?, ?, ?, 'enterprise', ?, ?, ?, ?)",
                   (org_id, req.name, slug, req.owner_email, req.slack_webhook or "", req.slack_channel or "", now))
        db_execute(conn, "INSERT INTO org_members (id, org_id, email, role, api_key, joined_at, created_at) VALUES (?, ?, ?, 'owner', ?, ?, ?)",
                   (member_id, org_id, req.owner_email, member_key, now, now))
        conn.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    return {"org_id": org_id, "slug": slug, "owner_api_key": member_key, "message": f"Organization '{req.name}' created"}

@app.get("/api/v1/orgs/{org_id}")
async def get_org(org_id: str, api_key: str = Depends(get_api_key)):
    org = get_org_by_id(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    conn = get_db()
    try:
        members = db_fetchall(conn, "SELECT id, email, role, api_key, joined_at FROM org_members WHERE org_id = ?", (org_id,))
    finally:
        conn.close()
    return {"org": org, "members": [{"id": m[0], "email": m[1], "role": m[2], "api_key": m[3][:8]+"...", "joined_at": m[4]} for m in members]}

@app.put("/api/v1/orgs/{org_id}")
async def update_org(org_id: str, req: UpdateOrgRequest, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        if req.slack_webhook is not None:
            db_execute(conn, "UPDATE orgs SET slack_webhook = ? WHERE id = ?", (req.slack_webhook, org_id))
        if req.slack_channel is not None:
            db_execute(conn, "UPDATE orgs SET slack_channel = ? WHERE id = ?", (req.slack_channel, org_id))
        if req.name is not None:
            db_execute(conn, "UPDATE orgs SET name = ? WHERE id = ?", (req.name, org_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": "updated"}

@app.post("/api/v1/orgs/{org_id}/invite")
async def invite_member(org_id: str, req: InviteMemberRequest, api_key: str = Depends(get_api_key)):
    """Invite a team member to the org."""
    token = str(uuid.uuid4()).replace("-", "")
    invite_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = datetime.fromtimestamp(now.timestamp() + 7*24*3600, tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn, "INSERT INTO org_invites (id, org_id, email, role, token, created_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (invite_id, org_id, req.email, req.role, token, api_key, expires, now.isoformat()))
        conn.commit()
    finally:
        conn.close()
    base_url = os.getenv("BASE_URL", "https://apex-swarm-v2-production.up.railway.app")
    invite_url = f"{base_url}/accept-invite?token={token}"
    return {"invite_url": invite_url, "token": token, "email": req.email, "expires_at": expires}

@app.post("/api/v1/orgs/accept-invite")
async def accept_invite(req: AcceptInviteRequest):
    """Accept an org invite and get an API key."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        invite = db_fetchone(conn, "SELECT id, org_id, email, role, expires_at, used FROM org_invites WHERE token = ?", (req.token,))
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite[5]:
            raise HTTPException(status_code=400, detail="Invite already used")
        if invite[4] < now:
            raise HTTPException(status_code=400, detail="Invite expired")
        member_id = str(uuid.uuid4())
        member_key = f"ak-{str(uuid.uuid4()).replace('-', '')[:32]}"
        db_execute(conn, "INSERT INTO org_members (id, org_id, email, role, api_key, joined_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (member_id, invite[1], req.email, invite[2], member_key, now, now))
        db_execute(conn, "UPDATE org_invites SET used = 1 WHERE id = ?", (invite[0],))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    return {"api_key": member_key, "org_id": invite[1], "role": invite[2], "message": "Welcome to the team!"}

@app.get("/api/v1/orgs/{org_id}/members")
async def list_members(org_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        members = db_fetchall(conn, "SELECT id, email, role, api_key, joined_at FROM org_members WHERE org_id = ?", (org_id,))
    finally:
        conn.close()
    return {"members": [{"id": m[0], "email": m[1], "role": m[2], "api_key": m[3][:8]+"...", "joined_at": m[4]} for m in members]}

@app.delete("/api/v1/orgs/{org_id}/members/{member_id}")
async def remove_member(org_id: str, member_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        db_execute(conn, "DELETE FROM org_members WHERE id = ? AND org_id = ?", (member_id, org_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": "removed"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── API ENDPOINTS ────────────────────────────────────────


# ─── AUTH ENDPOINTS ────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = ""

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/v1/auth/signup")
async def auth_signup(req: SignupRequest, request: Request):
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    uid = str(uuid.uuid4())
    ak = "ak-" + str(uuid.uuid4()).replace("-","")[:32]
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO users (id,email,password_hash,tier,api_key,created_at) VALUES (?,?,?,'free',?,?)",
                   (uid,req.email.lower().strip(),hash_password(req.password),ak,now))
        conn.commit()
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(400,"Email already registered")
        raise HTTPException(400,str(e))
    finally:
        conn.close()
    tok = make_token(uid)
    exp = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+30*86400,tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO sessions (id,user_id,token,expires_at,created_at) VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()),uid,tok,exp,now))
        conn.commit()
    finally:
        conn.close()
    log_audit(req.email,"signup","user",uid,uid,"",(request.client.host if request.client else ""))
    return {"token":tok,"api_key":ak,"email":req.email,"tier":"free"}

@app.post("/api/v1/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    conn = get_db()
    try:
        row = db_fetchone(conn,"SELECT id,email,password_hash,tier,api_key,org_id,role,active FROM users WHERE email=?",
                         (req.email.lower().strip(),))
    finally:
        conn.close()
    if not row or not row[7]:
        raise HTTPException(401,"Invalid email or password")
    if not verify_password(req.password,row[2]):
        raise HTTPException(401,"Invalid email or password")
    tok = make_token(row[0])
    now = datetime.now(timezone.utc).isoformat()
    exp = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+30*86400,tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO sessions (id,user_id,token,expires_at,created_at) VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()),row[0],tok,exp,now))
        conn.commit()
    finally:
        conn.close()
    log_audit(row[1],"login","session","",row[0],row[5] or "",(request.client.host if request.client else ""))
    return {"token":tok,"api_key":row[4],"email":row[1],"tier":row[3],"org_id":row[5],"role":row[6]}

@app.post("/api/v1/auth/logout")
async def auth_logout(request: Request):
    tok = request.headers.get("X-Session-Token","")
    if tok:
        conn = get_db()
        try:
            db_execute(conn,"DELETE FROM sessions WHERE token=?",(tok,))
            conn.commit()
        finally:
            conn.close()
    return {"status":"logged out"}

@app.get("/api/v1/auth/me")
async def auth_me(request: Request):
    tok = request.headers.get("X-Session-Token","") or request.headers.get("Authorization","").replace("Bearer ","")
    if not tok:
        raise HTTPException(401,"Not authenticated")
    user = get_user_by_token(tok)
    if not user:
        raise HTTPException(401,"Invalid or expired session")
    return user

@app.get("/api/v1/auth/google")
async def google_start():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400,"Google OAuth not configured. Set GOOGLE_CLIENT_ID env var.")
    from urllib.parse import urlencode
    from fastapi.responses import RedirectResponse
    params = {"client_id":GOOGLE_CLIENT_ID,"redirect_uri":BASE_URL+"/api/v1/auth/google/callback",
              "response_type":"code","scope":"openid email profile","access_type":"offline"}
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?"+urlencode(params))

@app.get("/api/v1/auth/google/callback")
async def google_callback(code: str = None, error: str = None):
    from fastapi.responses import RedirectResponse, HTMLResponse as _HR
    if error or not code:
        return RedirectResponse("/login?error=google_failed")
    try:
        async with httpx.AsyncClient() as client:
            tr = await client.post("https://oauth2.googleapis.com/token",data={
                "code":code,"client_id":GOOGLE_CLIENT_ID,"client_secret":GOOGLE_CLIENT_SECRET,
                "redirect_uri":BASE_URL+"/api/v1/auth/google/callback","grant_type":"authorization_code"})
            tokens = tr.json()
            ur = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization":"Bearer "+tokens.get("access_token","")})
            gu = ur.json()
        email = gu.get("email","")
        gid = gu.get("id","")
        if not email:
            return RedirectResponse("/login?error=no_email")
        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        try:
            row = db_fetchone(conn,"SELECT id,api_key,tier FROM users WHERE email=?",(email,))
            if row:
                uid,ak,tier = row[0],row[1],row[2]
                db_execute(conn,"UPDATE users SET google_id=? WHERE id=?",(gid,uid))
            else:
                uid = str(uuid.uuid4())
                ak = "ak-"+str(uuid.uuid4()).replace("-","")[:32]
                db_execute(conn,"INSERT INTO users (id,email,password_hash,tier,api_key,google_id,created_at) VALUES (?,?,?,'free',?,?,?)",
                           (uid,email,"",ak,gid,now))
                tier = "free"
            stok = make_token(uid)
            exp = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+30*86400,tz=timezone.utc).isoformat()
            db_execute(conn,"INSERT INTO sessions (id,user_id,token,expires_at,created_at) VALUES (?,?,?,?,?)",
                       (str(uuid.uuid4()),uid,stok,exp,now))
            conn.commit()
        finally:
            conn.close()
        log_audit(email,"google_login","session",gid,uid,"")
        return _HR(
            "<script>"
            "localStorage.setItem('apex_token','" + stok + "');"
            "localStorage.setItem('apex_key','" + ak + "');"
            "localStorage.setItem('apex_email','" + email + "');"
            "window.location.href='/dashboard';</script>"
        )
    except Exception as e:
        logger.error("Google OAuth: "+str(e))
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login?error=oauth_error")

# ─── BILLING ────────────────────────────────────────────

@app.post("/api/v1/billing/checkout")
async def billing_checkout(request: Request):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(400,"Stripe not configured. Add STRIPE_SECRET_KEY to env vars.")
    data = await request.json()
    tier = data.get("tier","starter")
    tok = request.headers.get("X-Session-Token","")
    user = get_user_by_token(tok)
    if not user:
        raise HTTPException(401,"Not authenticated")
    pm = {"starter":STRIPE_STARTER_PRICE,"pro":STRIPE_PRO_PRICE,"enterprise":STRIPE_ENTERPRISE_PRICE}
    pid = pm.get(tier)
    if not pid:
        raise HTTPException(400,"Invalid tier")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post("https://api.stripe.com/v1/checkout/sessions",
                auth=(STRIPE_SECRET_KEY,""),
                data={"mode":"subscription","line_items[0][price]":pid,"line_items[0][quantity]":"1",
                      "customer_email":user["email"],
                      "success_url":BASE_URL+"/dashboard?upgraded=1",
                      "cancel_url":BASE_URL+"/pricing",
                      "metadata[user_id]":user["user_id"],"metadata[tier]":tier})
            res = r.json()
            return {"checkout_url":res.get("url"),"session_id":res.get("id")}
    except Exception as e:
        raise HTTPException(500,str(e))

@app.post("/api/v1/billing/webhook")
async def billing_webhook(request: Request):
    try:
        payload = await request.body()
        event = _json.loads(payload)
        etype = event.get("type","")
        if etype in ("checkout.session.completed","customer.subscription.updated"):
            obj = event.get("data",{}).get("object",{})
            uid = obj.get("metadata",{}).get("user_id","")
            tier = obj.get("metadata",{}).get("tier","starter")
            cid = obj.get("customer","")
            sid = obj.get("subscription",obj.get("id",""))
            if uid:
                conn = get_db()
                try:
                    db_execute(conn,"UPDATE users SET tier=?,stripe_customer_id=?,stripe_subscription_id=? WHERE id=?",(tier,cid,sid,uid))
                    conn.commit()
                finally:
                    conn.close()
    except Exception as e:
        logger.error("Stripe webhook: "+str(e))
    return {"received":True}

@app.get("/api/v1/billing/status")
async def billing_status(request: Request):
    tok = request.headers.get("X-Session-Token","")
    user = get_user_by_token(tok)
    tier = user["tier"] if user else "free"
    limits = TIER_LIMITS.get(tier,{})
    return {"tier":tier,"limits":limits}

# ─── AUDIT LOG ──────────────────────────────────────────

@app.get("/api/v1/audit/logs")
async def get_audit_logs(request: Request, limit: int=100, offset: int=0):
    conn = get_db()
    try:
        rows = db_fetchall(conn,
            "SELECT id,user_email,org_id,action,resource,detail,ip,created_at FROM audit_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit,offset))
        total = db_fetchone(conn,"SELECT COUNT(*) FROM audit_log",())[0]
    finally:
        conn.close()
    return {"logs":[{"id":r[0],"user":r[1],"org_id":r[2],"action":r[3],"resource":r[4],"detail":r[5],"ip":r[6],"ts":r[7]} for r in rows],"total":total}

# ─── ORG MANAGEMENT ─────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str
    slug: str
    owner_email: str
    slack_webhook: Optional[str] = ""
    slack_channel: Optional[str] = ""

class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"

class AcceptInviteRequest(BaseModel):
    token: str
    email: str

@app.post("/api/v1/orgs")
async def create_org(req: CreateOrgRequest, api_key: str = Depends(get_api_key)):
    import re as _re
    slug = _re.sub(r'[^a-z0-9-]','-',req.slug.lower()).strip('-')
    oid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    mk = "ak-"+str(uuid.uuid4()).replace("-","")[:32]
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO orgs (id,name,slug,tier,owner_email,slack_webhook,slack_channel,created_at) VALUES (?,?,?,'enterprise',?,?,?,?)",
                   (oid,req.name,slug,req.owner_email,req.slack_webhook or "",req.slack_channel or "",now))
        db_execute(conn,"INSERT INTO org_members (id,org_id,email,role,api_key,joined_at,created_at) VALUES (?,?,?,'owner',?,?,?)",
                   (mid,oid,req.owner_email,mk,now,now))
        conn.commit()
    except Exception as e:
        raise HTTPException(400,str(e))
    finally:
        conn.close()
    return {"org_id":oid,"slug":slug,"owner_api_key":mk,"message":"Organization created"}

@app.post("/api/v1/orgs/{org_id}/invite")
async def invite_member(org_id: str, req: InviteMemberRequest, api_key: str = Depends(get_api_key)):
    tok = str(uuid.uuid4()).replace("-","")
    iid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    exp = datetime.fromtimestamp(now.timestamp()+7*86400,tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO org_invites (id,org_id,email,role,token,created_by,expires_at,created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (iid,org_id,req.email,req.role,tok,api_key,exp,now.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return {"invite_url":BASE_URL+"/accept-invite?token="+tok,"token":tok,"email":req.email,"expires_at":exp}

@app.post("/api/v1/orgs/accept-invite")
async def accept_invite(req: AcceptInviteRequest):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        inv = db_fetchone(conn,"SELECT id,org_id,email,role,expires_at,used FROM org_invites WHERE token=?",(req.token,))
        if not inv:
            raise HTTPException(404,"Invite not found")
        if inv[5]:
            raise HTTPException(400,"Invite already used")
        if inv[4] < now:
            raise HTTPException(400,"Invite expired")
        mid = str(uuid.uuid4())
        mk = "ak-"+str(uuid.uuid4()).replace("-","")[:32]
        db_execute(conn,"INSERT INTO org_members (id,org_id,email,role,api_key,joined_at,created_at) VALUES (?,?,?,?,?,?,?)",
                   (mid,inv[1],req.email,inv[3],mk,now,now))
        db_execute(conn,"UPDATE org_invites SET used=1 WHERE id=?",(inv[0],))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400,str(e))
    finally:
        conn.close()
    return {"api_key":mk,"org_id":inv[1],"role":inv[3],"message":"Welcome to the team!"}

@app.get("/api/v1/orgs/{org_id}")
async def get_org(org_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        org = db_fetchone(conn,"SELECT id,name,slug,tier,owner_email,slack_webhook,slack_channel FROM orgs WHERE id=?",(org_id,))
        members = db_fetchall(conn,"SELECT id,email,role,api_key,joined_at FROM org_members WHERE org_id=?",(org_id,))
    finally:
        conn.close()
    if not org:
        raise HTTPException(404,"Org not found")
    return {"org":{"id":org[0],"name":org[1],"slug":org[2],"tier":org[3]},
            "members":[{"id":m[0],"email":m[1],"role":m[2],"api_key":m[3][:8]+"...","joined_at":m[4]} for m in members]}

# ─── SLACK CONFIG ────────────────────────────────────────

@app.post("/api/v1/slack/configure")
async def configure_slack(request: Request, api_key: str = Depends(get_api_key)):
    data = await request.json()
    webhook = data.get("webhook_url","")
    channel = data.get("channel","#ai-workforce")
    member = get_member_by_key(api_key)
    if member:
        conn = get_db()
        try:
            db_execute(conn,"UPDATE orgs SET slack_webhook=?,slack_channel=? WHERE id=?",(webhook,channel,member["org_id"]))
            conn.commit()
        finally:
            conn.close()
        return {"status":"configured","scope":"org"}
    return {"status":"configured","scope":"global"}

@app.post("/api/v1/slack/test")
async def test_slack(request: Request):
    data = await request.json()
    webhook = data.get("webhook_url") or SLACK_WEBHOOK_URL
    if not webhook:
        raise HTTPException(400,"No Slack webhook configured")
    ok = await send_slack_message("APEX SWARM connected to Slack! Your AI workforce is ready.",webhook_url=webhook)
    return {"success":ok}

@app.post("/api/v1/slack/commands")
async def slack_commands(request: Request):
    form = await request.form()
    text = (form.get("text") or "").strip()
    user_name = form.get("user_name","unknown")
    response_url = form.get("response_url","")
    parts = text.split(None,2)
    action = parts[0].lower() if parts else "help"
    async def respond(msg):
        if response_url:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.post(response_url,json={"text":msg,"response_type":"in_channel"})
            except Exception:
                pass
    if action == "deploy" and len(parts) >= 3:
        agent_type = parts[1]
        task = parts[2]
        asyncio.create_task(respond("Deploying " + agent_type + " for: " + task))
        try:
            result = await execute_task(agent_type,task,"slack-"+user_name)
            await respond(agent_type + " result: " + (result or "")[:500])
        except Exception as e:
            await respond("Error: "+str(e))
        return {"response_type":"in_channel","text":"Processing..."}
    elif action == "status":
        running = [d for d in active_daemons.values() if d.get("status")=="running"]
        return {"response_type":"in_channel","text":"APEX SWARM: "+str(len(running))+" workers active"}
    elif action == "stop" and len(parts) >= 2:
        did = parts[1]
        if did in active_daemons:
            active_daemons[did]["status"] = "stopped"
            return {"response_type":"in_channel","text":"Stopped "+did[:8]}
        return {"response_type":"in_channel","text":"Worker not found"}
    return {"response_type":"in_channel","text":"/apex deploy <type> <task> | /apex status | /apex stop <id>"}


# ─── AUTH ENDPOINTS ────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = ""

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/v1/auth/signup")
async def auth_signup(req: SignupRequest, request: Request):
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    uid = str(uuid.uuid4())
    ak = "ak-" + str(uuid.uuid4()).replace("-","")[:32]
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO users (id,email,password_hash,tier,api_key,created_at) VALUES (?,?,?,'free',?,?)",
                   (uid,req.email.lower().strip(),hash_password(req.password),ak,now))
        conn.commit()
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(400,"Email already registered")
        raise HTTPException(400,str(e))
    finally:
        conn.close()
    tok = make_token(uid)
    exp = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+30*86400,tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO sessions (id,user_id,token,expires_at,created_at) VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()),uid,tok,exp,now))
        conn.commit()
    finally:
        conn.close()
    log_audit(req.email,"signup","user",uid,uid,"",(request.client.host if request.client else ""))
    return {"token":tok,"api_key":ak,"email":req.email,"tier":"free"}

@app.post("/api/v1/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    conn = get_db()
    try:
        row = db_fetchone(conn,"SELECT id,email,password_hash,tier,api_key,org_id,role,active FROM users WHERE email=?",
                         (req.email.lower().strip(),))
    finally:
        conn.close()
    if not row or not row[7]:
        raise HTTPException(401,"Invalid email or password")
    if not verify_password(req.password,row[2]):
        raise HTTPException(401,"Invalid email or password")
    tok = make_token(row[0])
    now = datetime.now(timezone.utc).isoformat()
    exp = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+30*86400,tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO sessions (id,user_id,token,expires_at,created_at) VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()),row[0],tok,exp,now))
        conn.commit()
    finally:
        conn.close()
    log_audit(row[1],"login","session","",row[0],row[5] or "",(request.client.host if request.client else ""))
    return {"token":tok,"api_key":row[4],"email":row[1],"tier":row[3],"org_id":row[5],"role":row[6]}

@app.post("/api/v1/auth/logout")
async def auth_logout(request: Request):
    tok = request.headers.get("X-Session-Token","")
    if tok:
        conn = get_db()
        try:
            db_execute(conn,"DELETE FROM sessions WHERE token=?",(tok,))
            conn.commit()
        finally:
            conn.close()
    return {"status":"logged out"}

@app.get("/api/v1/auth/me")
async def auth_me(request: Request):
    tok = request.headers.get("X-Session-Token","") or request.headers.get("Authorization","").replace("Bearer ","")
    if not tok:
        raise HTTPException(401,"Not authenticated")
    user = get_user_by_token(tok)
    if not user:
        raise HTTPException(401,"Invalid or expired session")
    return user

@app.get("/api/v1/auth/google")
async def google_start():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400,"Google OAuth not configured. Set GOOGLE_CLIENT_ID env var.")
    from urllib.parse import urlencode
    from fastapi.responses import RedirectResponse
    params = {"client_id":GOOGLE_CLIENT_ID,"redirect_uri":BASE_URL+"/api/v1/auth/google/callback",
              "response_type":"code","scope":"openid email profile","access_type":"offline"}
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?"+urlencode(params))

@app.get("/api/v1/auth/google/callback")
async def google_callback(code: str = None, error: str = None):
    from fastapi.responses import RedirectResponse, HTMLResponse as _HR
    if error or not code:
        return RedirectResponse("/login?error=google_failed")
    try:
        async with httpx.AsyncClient() as client:
            tr = await client.post("https://oauth2.googleapis.com/token",data={
                "code":code,"client_id":GOOGLE_CLIENT_ID,"client_secret":GOOGLE_CLIENT_SECRET,
                "redirect_uri":BASE_URL+"/api/v1/auth/google/callback","grant_type":"authorization_code"})
            tokens = tr.json()
            ur = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization":"Bearer "+tokens.get("access_token","")})
            gu = ur.json()
        email = gu.get("email","")
        gid = gu.get("id","")
        if not email:
            return RedirectResponse("/login?error=no_email")
        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        try:
            row = db_fetchone(conn,"SELECT id,api_key,tier FROM users WHERE email=?",(email,))
            if row:
                uid,ak,tier = row[0],row[1],row[2]
                db_execute(conn,"UPDATE users SET google_id=? WHERE id=?",(gid,uid))
            else:
                uid = str(uuid.uuid4())
                ak = "ak-"+str(uuid.uuid4()).replace("-","")[:32]
                db_execute(conn,"INSERT INTO users (id,email,password_hash,tier,api_key,google_id,created_at) VALUES (?,?,?,'free',?,?,?)",
                           (uid,email,"",ak,gid,now))
                tier = "free"
            stok = make_token(uid)
            exp = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+30*86400,tz=timezone.utc).isoformat()
            db_execute(conn,"INSERT INTO sessions (id,user_id,token,expires_at,created_at) VALUES (?,?,?,?,?)",
                       (str(uuid.uuid4()),uid,stok,exp,now))
            conn.commit()
        finally:
            conn.close()
        log_audit(email,"google_login","session",gid,uid,"")
        return _HR(
            "<script>"
            "localStorage.setItem('apex_token','" + stok + "');"
            "localStorage.setItem('apex_key','" + ak + "');"
            "localStorage.setItem('apex_email','" + email + "');"
            "window.location.href='/dashboard';</script>"
        )
    except Exception as e:
        logger.error("Google OAuth: "+str(e))
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login?error=oauth_error")

# ─── BILLING ────────────────────────────────────────────

@app.post("/api/v1/billing/checkout")
async def billing_checkout(request: Request):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(400,"Stripe not configured. Add STRIPE_SECRET_KEY to env vars.")
    data = await request.json()
    tier = data.get("tier","starter")
    tok = request.headers.get("X-Session-Token","")
    user = get_user_by_token(tok)
    if not user:
        raise HTTPException(401,"Not authenticated")
    pm = {"starter":STRIPE_STARTER_PRICE,"pro":STRIPE_PRO_PRICE,"enterprise":STRIPE_ENTERPRISE_PRICE}
    pid = pm.get(tier)
    if not pid:
        raise HTTPException(400,"Invalid tier")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post("https://api.stripe.com/v1/checkout/sessions",
                auth=(STRIPE_SECRET_KEY,""),
                data={"mode":"subscription","line_items[0][price]":pid,"line_items[0][quantity]":"1",
                      "customer_email":user["email"],
                      "success_url":BASE_URL+"/dashboard?upgraded=1",
                      "cancel_url":BASE_URL+"/pricing",
                      "metadata[user_id]":user["user_id"],"metadata[tier]":tier})
            res = r.json()
            return {"checkout_url":res.get("url"),"session_id":res.get("id")}
    except Exception as e:
        raise HTTPException(500,str(e))

@app.post("/api/v1/billing/webhook")
async def billing_webhook(request: Request):
    try:
        payload = await request.body()
        event = _json.loads(payload)
        etype = event.get("type","")
        if etype in ("checkout.session.completed","customer.subscription.updated"):
            obj = event.get("data",{}).get("object",{})
            uid = obj.get("metadata",{}).get("user_id","")
            tier = obj.get("metadata",{}).get("tier","starter")
            cid = obj.get("customer","")
            sid = obj.get("subscription",obj.get("id",""))
            if uid:
                conn = get_db()
                try:
                    db_execute(conn,"UPDATE users SET tier=?,stripe_customer_id=?,stripe_subscription_id=? WHERE id=?",(tier,cid,sid,uid))
                    conn.commit()
                finally:
                    conn.close()
    except Exception as e:
        logger.error("Stripe webhook: "+str(e))
    return {"received":True}

@app.get("/api/v1/billing/status")
async def billing_status(request: Request):
    tok = request.headers.get("X-Session-Token","")
    user = get_user_by_token(tok)
    tier = user["tier"] if user else "free"
    limits = TIER_LIMITS.get(tier,{})
    return {"tier":tier,"limits":limits}

# ─── AUDIT LOG ──────────────────────────────────────────

@app.get("/api/v1/audit/logs")
async def get_audit_logs(request: Request, limit: int=100, offset: int=0):
    conn = get_db()
    try:
        rows = db_fetchall(conn,
            "SELECT id,user_email,org_id,action,resource,detail,ip,created_at FROM audit_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit,offset))
        total = db_fetchone(conn,"SELECT COUNT(*) FROM audit_log",())[0]
    finally:
        conn.close()
    return {"logs":[{"id":r[0],"user":r[1],"org_id":r[2],"action":r[3],"resource":r[4],"detail":r[5],"ip":r[6],"ts":r[7]} for r in rows],"total":total}

# ─── ORG MANAGEMENT ─────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str
    slug: str
    owner_email: str
    slack_webhook: Optional[str] = ""
    slack_channel: Optional[str] = ""

class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"

class AcceptInviteRequest(BaseModel):
    token: str
    email: str

@app.post("/api/v1/orgs")
async def create_org(req: CreateOrgRequest, api_key: str = Depends(get_api_key)):
    import re as _re
    slug = _re.sub(r'[^a-z0-9-]','-',req.slug.lower()).strip('-')
    oid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    mk = "ak-"+str(uuid.uuid4()).replace("-","")[:32]
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO orgs (id,name,slug,tier,owner_email,slack_webhook,slack_channel,created_at) VALUES (?,?,?,'enterprise',?,?,?,?)",
                   (oid,req.name,slug,req.owner_email,req.slack_webhook or "",req.slack_channel or "",now))
        db_execute(conn,"INSERT INTO org_members (id,org_id,email,role,api_key,joined_at,created_at) VALUES (?,?,?,'owner',?,?,?)",
                   (mid,oid,req.owner_email,mk,now,now))
        conn.commit()
    except Exception as e:
        raise HTTPException(400,str(e))
    finally:
        conn.close()
    return {"org_id":oid,"slug":slug,"owner_api_key":mk,"message":"Organization created"}

@app.post("/api/v1/orgs/{org_id}/invite")
async def invite_member(org_id: str, req: InviteMemberRequest, api_key: str = Depends(get_api_key)):
    tok = str(uuid.uuid4()).replace("-","")
    iid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    exp = datetime.fromtimestamp(now.timestamp()+7*86400,tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        db_execute(conn,"INSERT INTO org_invites (id,org_id,email,role,token,created_by,expires_at,created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (iid,org_id,req.email,req.role,tok,api_key,exp,now.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return {"invite_url":BASE_URL+"/accept-invite?token="+tok,"token":tok,"email":req.email,"expires_at":exp}

@app.post("/api/v1/orgs/accept-invite")
async def accept_invite(req: AcceptInviteRequest):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        inv = db_fetchone(conn,"SELECT id,org_id,email,role,expires_at,used FROM org_invites WHERE token=?",(req.token,))
        if not inv:
            raise HTTPException(404,"Invite not found")
        if inv[5]:
            raise HTTPException(400,"Invite already used")
        if inv[4] < now:
            raise HTTPException(400,"Invite expired")
        mid = str(uuid.uuid4())
        mk = "ak-"+str(uuid.uuid4()).replace("-","")[:32]
        db_execute(conn,"INSERT INTO org_members (id,org_id,email,role,api_key,joined_at,created_at) VALUES (?,?,?,?,?,?,?)",
                   (mid,inv[1],req.email,inv[3],mk,now,now))
        db_execute(conn,"UPDATE org_invites SET used=1 WHERE id=?",(inv[0],))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400,str(e))
    finally:
        conn.close()
    return {"api_key":mk,"org_id":inv[1],"role":inv[3],"message":"Welcome to the team!"}

@app.get("/api/v1/orgs/{org_id}")
async def get_org(org_id: str, api_key: str = Depends(get_api_key)):
    conn = get_db()
    try:
        org = db_fetchone(conn,"SELECT id,name,slug,tier,owner_email,slack_webhook,slack_channel FROM orgs WHERE id=?",(org_id,))
        members = db_fetchall(conn,"SELECT id,email,role,api_key,joined_at FROM org_members WHERE org_id=?",(org_id,))
    finally:
        conn.close()
    if not org:
        raise HTTPException(404,"Org not found")
    return {"org":{"id":org[0],"name":org[1],"slug":org[2],"tier":org[3]},
            "members":[{"id":m[0],"email":m[1],"role":m[2],"api_key":m[3][:8]+"...","joined_at":m[4]} for m in members]}

# ─── SLACK CONFIG ────────────────────────────────────────

@app.post("/api/v1/slack/configure")
async def configure_slack(request: Request, api_key: str = Depends(get_api_key)):
    data = await request.json()
    webhook = data.get("webhook_url","")
    channel = data.get("channel","#ai-workforce")
    member = get_member_by_key(api_key)
    if member:
        conn = get_db()
        try:
            db_execute(conn,"UPDATE orgs SET slack_webhook=?,slack_channel=? WHERE id=?",(webhook,channel,member["org_id"]))
            conn.commit()
        finally:
            conn.close()
        return {"status":"configured","scope":"org"}
    return {"status":"configured","scope":"global"}

@app.post("/api/v1/slack/test")
async def test_slack(request: Request):
    data = await request.json()
    webhook = data.get("webhook_url") or SLACK_WEBHOOK_URL
    if not webhook:
        raise HTTPException(400,"No Slack webhook configured")
    ok = await send_slack_message("APEX SWARM connected to Slack! Your AI workforce is ready.",webhook_url=webhook)
    return {"success":ok}

@app.post("/api/v1/slack/commands")
async def slack_commands(request: Request):
    form = await request.form()
    text = (form.get("text") or "").strip()
    user_name = form.get("user_name","unknown")
    response_url = form.get("response_url","")
    parts = text.split(None,2)
    action = parts[0].lower() if parts else "help"
    async def respond(msg):
        if response_url:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.post(response_url,json={"text":msg,"response_type":"in_channel"})
            except Exception:
                pass
    if action == "deploy" and len(parts) >= 3:
        agent_type = parts[1]
        task = parts[2]
        asyncio.create_task(respond("Deploying " + agent_type + " for: " + task))
        try:
            result = await execute_task(agent_type,task,"slack-"+user_name)
            await respond(agent_type + " result: " + (result or "")[:500])
        except Exception as e:
            await respond("Error: "+str(e))
        return {"response_type":"in_channel","text":"Processing..."}
    elif action == "status":
        running = [d for d in active_daemons.values() if d.get("status")=="running"]
        return {"response_type":"in_channel","text":"APEX SWARM: "+str(len(running))+" workers active"}
    elif action == "stop" and len(parts) >= 2:
        did = parts[1]
        if did in active_daemons:
            active_daemons[did]["status"] = "stopped"
            return {"response_type":"in_channel","text":"Stopped "+did[:8]}
        return {"response_type":"in_channel","text":"Worker not found"}
    return {"response_type":"in_channel","text":"/apex deploy <type> <task> | /apex status | /apex stop <id>"}

@app.get("/api/v1/health")
async def health():
    return {
        "status": "healthy",
        "version": VERSION,
        "agents": len(AGENTS),
        "tools": TOOLS_AVAILABLE,
        "chains": CHAINS_AVAILABLE,
        "knowledge": SMART_KNOWLEDGE,
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
        "a2a_protocol": A2A_AVAILABLE,
        "autonomous_goals": GOALS_AVAILABLE,
        "enterprise": ENTERPRISE,
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
            import json as _json
            for past in event_bus.get_history(limit=20):
                yield f"data: {_json.dumps(past)}\n\n"

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


@app.get("/api/v1/admin/users")
async def admin_list_users(current_user: dict = Depends(get_validated_user)):
    if current_user.get("email") not in ["revcole@gmail.com", "admin@swarmsfall.com"] and current_user.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    with get_db() as conn:
        rows = conn.execute("SELECT id, email, tier, active, created_at FROM users ORDER BY created_at DESC").fetchall()
    return {"users": [{"id":r[0],"email":r[1],"tier":r[2],"active":r[3],"created_at":r[4]} for r in rows]}

@app.post("/api/v1/admin/users/{user_id}/tier")
async def admin_set_tier(user_id: str, request: Request, current_user: dict = Depends(get_validated_user)):
    if current_user.get("email") not in ["revcole@gmail.com", "admin@swarmsfall.com"] and current_user.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    body = await request.json()
    tier = body.get("tier", "free")
    with get_db() as conn:
        conn.execute("UPDATE users SET tier=? WHERE id=?", (tier, user_id))
        conn.commit()
    return {"ok": True, "tier": tier}

@app.post("/api/v1/admin/users/{user_id}/suspend")
async def admin_suspend_user(user_id: str, current_user: dict = Depends(get_validated_user)):
    if current_user.get("email") not in ["revcole@gmail.com", "admin@swarmsfall.com"] and current_user.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    with get_db() as conn:
        conn.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
        conn.commit()
    return {"ok": True}

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


# ─── AUTONOMOUS GOAL ENDPOINTS ───────────────────────────

class GoalRequest(BaseModel):
    title: str
    description: str
    budget_usd: float = 0.0
    org_roles: list = ["ceo", "researcher", "writer", "analyst"]
    model: Optional[str] = None
    auto_execute: bool = True


@app.post("/api/v1/goals")
async def create_goal(req: GoalRequest, api_key: str = Depends(get_api_key)):
    if not GOALS_AVAILABLE or not goal_engine:
        raise HTTPException(status_code=503, detail="Goal system not loaded")
    goal = await goal_engine.create_goal(
        title=req.title, description=req.description,
        user_api_key=api_key, budget_usd=req.budget_usd,
        org_roles=req.org_roles, model=req.model,
        auto_execute=req.auto_execute,
    )
    return goal.to_dict()


@app.get("/api/v1/goals")
async def list_goals(api_key: str = Depends(get_api_key)):
    if not GOALS_AVAILABLE or not goal_engine:
        return {"goals": []}
    return {"goals": goal_engine.list_goals(api_key)}


@app.get("/api/v1/goals/{goal_id}")
async def get_goal(goal_id: str):
    if not GOALS_AVAILABLE or not goal_engine:
        raise HTTPException(status_code=503)
    goal = goal_engine.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@app.get("/api/v1/goals/{goal_id}/report")
async def goal_report(goal_id: str, api_key: str = Depends(get_api_key)):
    if not GOALS_AVAILABLE or not goal_engine:
        raise HTTPException(status_code=503)
    report = await goal_engine.get_progress_report(goal_id)
    return {"report": report}


@app.post("/api/v1/goals/{goal_id}/pause")
async def pause_goal(goal_id: str, api_key: str = Depends(get_api_key)):
    if not GOALS_AVAILABLE or not goal_engine:
        raise HTTPException(status_code=503)
    goal_engine.pause_goal(goal_id)
    return {"status": "paused"}


@app.get("/api/v1/goals/stats/overview")
async def goal_stats():
    if not GOALS_AVAILABLE or not goal_engine:
        return {"total_goals": 0}
    return goal_engine.get_stats()


@app.get("/api/v1/roles")
async def list_roles():
    if not GOALS_AVAILABLE:
        return {"roles": []}
    return {"roles": [
        {"role_id": rid, "name": r["name"], "icon": r["icon"], "description": r["description"],
         "tool_count": len(r["tools"]), "can_delegate": r["can_delegate"],
         "email_permissions": EMAIL_PERMISSIONS.get(rid, {})}
        for rid, r in ROLES.items()
    ]}


@app.get("/api/v1/roles/{role_id}")
async def get_role(role_id: str):
    if not GOALS_AVAILABLE:
        raise HTTPException(status_code=503)
    role = ROLES.get(role_id)
    if not role:
        raise HTTPException(status_code=404)
    return {
        "role_id": role_id, **role,
        "email_permissions": EMAIL_PERMISSIONS.get(role_id, {}),
    }


# ─── A2A PROTOCOL ENDPOINTS ──────────────────────────────

class A2ARequest(BaseModel):
    task: str
    lead_agent: str = "research"
    model: Optional[str] = None
    strategy: Optional[str] = None
    max_subtasks: int = 5


@app.post("/api/v1/a2a/delegate")
async def a2a_delegate(req: A2ARequest, api_key: str = Depends(get_api_key)):
    """Decompose a complex task and delegate to multiple agents."""
    if not A2A_AVAILABLE or not a2a_engine:
        raise HTTPException(status_code=503, detail="A2A protocol not loaded")
    plan = await a2a_engine.decompose_and_delegate(
        task=req.task, lead_agent=req.lead_agent,
        user_api_key=api_key, model=req.model, max_subtasks=req.max_subtasks,
    )
    return plan.to_dict()


@app.get("/api/v1/a2a/plans")
async def list_a2a_plans():
    if not A2A_AVAILABLE or not a2a_engine:
        return {"plans": []}
    return {"plans": a2a_engine.get_active_plans()}


@app.get("/api/v1/a2a/plans/{plan_id}")
async def get_a2a_plan(plan_id: str):
    if not A2A_AVAILABLE or not a2a_engine:
        raise HTTPException(status_code=503, detail="A2A not loaded")
    plan = a2a_engine.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.get("/api/v1/a2a/plans/{plan_id}/messages")
async def get_a2a_messages(plan_id: str):
    if not A2A_AVAILABLE or not a2a_engine:
        return {"messages": []}
    return {"messages": a2a_engine.get_plan_messages(plan_id)}


@app.get("/api/v1/a2a/stats")
async def a2a_stats():
    if not A2A_AVAILABLE or not a2a_engine:
        return {"total_plans": 0}
    return a2a_engine.get_stats()


# ─── ENTERPRISE ENDPOINTS ─────────────────────────────────

@app.post("/api/v1/deploy/sync")
async def deploy_agent_sync(req: DeployRequest, api_key: str = Depends(get_api_key)):
    """Deploy agent and WAIT for result (synchronous). For testing/debugging."""
    if req.agent_type not in AGENTS and not req.agent_type.startswith("mp:"):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent_type}")

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

    try:
        await execute_task(agent_id, req.agent_type, req.task_description, api_key, model=req.model)
    except Exception as e:
        import traceback
        return {"agent_id": agent_id, "status": "error", "error": str(e), "traceback": traceback.format_exc()}

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT status, result FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
    finally:
        conn.close()

    return {
        "agent_id": agent_id,
        "status": row[0] if row else "unknown",
        "result": row[1] if row else None,
    }


@app.get("/api/v1/metrics")
async def get_metrics(api_key: str = Depends(get_api_key)):
    if not ENTERPRISE or not metrics_collector:
        return {"error": "Metrics not available"}
    return metrics_collector.get_summary()


@app.get("/api/v1/metrics/agents")
async def get_agent_metrics(api_key: str = Depends(get_api_key)):
    if not ENTERPRISE or not metrics_collector:
        return {"counts": {}, "latencies": {}}
    return metrics_collector.get_agent_metrics()


@app.get("/api/v1/audit")
async def get_audit_log(limit: int = 50, flagged_only: bool = False, api_key: str = Depends(get_api_key)):
    if not ENTERPRISE or not audit_log:
        return {"events": []}
    return {"events": audit_log.get_recent(limit, flagged_only)}


@app.get("/api/v1/circuit-breakers")
async def get_circuit_breakers(api_key: str = Depends(get_api_key)):
    if not ENTERPRISE:
        return {"breakers": []}
    return {"breakers": [cb.get_status() for cb in circuit_breakers.values()]}


@app.get("/api/v1/docs/openapi.json")
async def openapi_spec():
    if not ENTERPRISE:
        return {"info": {"title": "APEX SWARM", "version": VERSION}}
    return get_api_docs()


@app.get("/api/v1/docs", response_class=HTMLResponse)
async def api_docs_page():
    """Interactive API documentation powered by Swagger UI."""
    return HTMLResponse(f"""<!DOCTYPE html><html><head><title>APEX SWARM API Docs</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui.min.css">
</head><body><div id="swagger-ui"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-bundle.min.js"></script>
<script>SwaggerUIBundle({{url:'/api/v1/docs/openapi.json',dom_id:'#swagger-ui',deepLinking:true}})</script>
</body></html>""")


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


@app.post("/api/v1/slack/configure")
async def configure_slack(request: Request, api_key: str = Depends(get_api_key)):
    """Configure Slack webhook for this user/org."""
    data = await request.json()
    webhook = data.get("webhook_url", "")
    channel = data.get("channel", "#ai-workforce")
    # If org member, update their org
    member = get_member_by_key(api_key)
    if member:
        conn = get_db()
        try:
            db_execute(conn, "UPDATE orgs SET slack_webhook = ?, slack_channel = ? WHERE id = ?",
                      (webhook, channel, member["org_id"]))
            conn.commit()
        finally:
            conn.close()
        return {"status": "configured", "scope": "org", "org_id": member["org_id"]}
    return {"status": "configured", "scope": "global", "note": "Set SLACK_WEBHOOK_URL env var for persistent config"}

@app.post("/api/v1/slack/test")
async def test_slack(request: Request, api_key: str = Depends(get_api_key)):
    """Send a test message to Slack."""
    data = await request.json()
    webhook = data.get("webhook_url") or SLACK_WEBHOOK_URL
    if not webhook:
        raise HTTPException(status_code=400, detail="No Slack webhook configured")
    ok = await send_slack_message("✅ APEX SWARM connected to Slack! Your AI workforce is ready.", webhook_url=webhook)
    return {"success": ok}


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



# ─── STATIC HTML PAGES ───────────────────────────────────
SIGNUP_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Sign Up — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}\n.card{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:100%;max-width:440px}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0;text-transform:uppercase;margin-bottom:10px}\nh1{font-size:26px;font-weight:800;margin-bottom:6px}\n.sub{color:#888;font-size:14px;margin-bottom:28px}\nlabel{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:6px}\ninput{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 14px;color:#e8e8f0;font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-bottom:18px;transition:border-color 0.2s}\ninput:focus{border-color:#00f0a0}\n.btn{display:block;width:100%;background:#00f0a0;color:#0a0a0f;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:\'Inter\',sans-serif;transition:opacity 0.2s;text-align:center;text-decoration:none;margin-bottom:12px}\n.btn:hover{opacity:0.9}\n.btn.outline{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#e8e8f0;display:flex;align-items:center;justify-content:center;gap:10px}\n.err{color:#ff4d6d;font-size:13px;margin-bottom:16px;display:none;padding:10px;background:rgba(255,77,109,0.1);border-radius:6px}\n.link{text-align:center;margin-top:16px;font-size:13px;color:#888}\n.link a{color:#00f0a0;text-decoration:none}\n.divider{display:flex;align-items:center;gap:12px;margin:16px 0;color:#555;font-size:12px}\n.divider:before,.divider:after{content:\'\';flex:1;height:1px;background:rgba(255,255,255,0.08)}\n.features{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}\n.feat{font-size:12px;color:#aaa;display:flex;align-items:center;gap:5px}\n.feat span{color:#00f0a0}\n</style>\n</head>\n<body>\n<div class="card">\n  <div class="logo">APEX SWARM</div>\n  <h1>Start your AI workforce</h1>\n  <p class="sub">Deploy 66+ autonomous AI agents in 60 seconds</p>\n  <div class="features">\n    <div class="feat"><span>✓</span> Free to start</div>\n    <div class="feat"><span>✓</span> No credit card</div>\n    <div class="feat"><span>✓</span> 24/7 workers</div>\n  </div>\n  <a href="/api/v1/auth/google" class="btn outline">\n    <svg width="18" height="18" viewBox="0 0 18 18"><path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 002.38-5.88c0-.57-.05-.66-.15-1.18z"/><path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2a4.8 4.8 0 01-7.18-2.54H1.83v2.07A8 8 0 008.98 17z"/><path fill="#FBBC05" d="M4.5 10.52a4.8 4.8 0 010-3.04V5.41H1.83a8 8 0 000 7.18l2.67-2.07z"/><path fill="#EA4335" d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 001.83 5.4L4.5 7.49a4.77 4.77 0 014.48-3.3z"/></svg>\n    Continue with Google\n  </a>\n  <div class="divider">or</div>\n  <div class="err" id="err"></div>\n  <label>Email</label>\n  <input type="email" id="email" placeholder="you@company.com" autofocus>\n  <label>Password</label>\n  <input type="password" id="password" placeholder="At least 8 characters">\n  <button class="btn" onclick="doSignup()">Create Free Account</button>\n  <div class="link">Already have an account? <a href="/login">Sign in</a> · <a href="/pricing">See pricing</a></div>\n</div>\n<script>\nasync function doSignup() {\n  const email = document.getElementById(\'email\').value.trim();\n  const password = document.getElementById(\'password\').value;\n  const err = document.getElementById(\'err\');\n  err.style.display = \'none\';\n  if (!email || !password) { err.textContent = \'Please fill in all fields\'; err.style.display = \'block\'; return; }\n  try {\n    const r = await fetch(\'/api/v1/auth/signup\', {\n      method: \'POST\', headers: {\'Content-Type\': \'application/json\'},\n      body: JSON.stringify({email, password})\n    });\n    const data = await r.json();\n    if (!r.ok) { err.textContent = data.detail || \'Signup failed\'; err.style.display = \'block\'; return; }\n    localStorage.setItem(\'apex_token\', data.token);\n    localStorage.setItem(\'apex_key\', data.api_key);\n    localStorage.setItem(\'apex_email\', data.email);\n    window.location.href = \'/dashboard\';\n  } catch(e) { err.textContent = \'Network error — please try again\'; err.style.display = \'block\'; }\n}\ndocument.addEventListener(\'keydown\', e => { if(e.key === \'Enter\') doSignup(); });\n</script>\n</body></html>\n'
LOGIN_HTML_NEW = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Sign In — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}\n.card{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:100%;max-width:440px}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0;text-transform:uppercase;margin-bottom:10px}\nh1{font-size:26px;font-weight:800;margin-bottom:6px}\n.sub{color:#888;font-size:14px;margin-bottom:28px}\nlabel{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:6px}\ninput{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 14px;color:#e8e8f0;font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-bottom:18px;transition:border-color 0.2s}\ninput:focus{border-color:#00f0a0}\n.btn{display:block;width:100%;background:#00f0a0;color:#0a0a0f;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:\'Inter\',sans-serif;transition:opacity 0.2s;text-align:center;text-decoration:none;margin-bottom:12px}\n.btn:hover{opacity:0.9}\n.btn.outline{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#e8e8f0;display:flex;align-items:center;justify-content:center;gap:10px}\n.err{color:#ff4d6d;font-size:13px;margin-bottom:16px;display:none;padding:10px;background:rgba(255,77,109,0.1);border-radius:6px}\n.link{text-align:center;margin-top:16px;font-size:13px;color:#888}\n.link a{color:#00f0a0;text-decoration:none}\n.divider{display:flex;align-items:center;gap:12px;margin:16px 0;color:#555;font-size:12px}\n.divider:before,.divider:after{content:\'\';flex:1;height:1px;background:rgba(255,255,255,0.08)}\n</style>\n</head>\n<body>\n<div class="card">\n  <div class="logo">APEX SWARM</div>\n  <h1>Welcome back</h1>\n  <p class="sub">Sign in to your AI workforce</p>\n  <a href="/api/v1/auth/google" class="btn outline">\n    <svg width="18" height="18" viewBox="0 0 18 18"><path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 002.38-5.88c0-.57-.05-.66-.15-1.18z"/><path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2a4.8 4.8 0 01-7.18-2.54H1.83v2.07A8 8 0 008.98 17z"/><path fill="#FBBC05" d="M4.5 10.52a4.8 4.8 0 010-3.04V5.41H1.83a8 8 0 000 7.18l2.67-2.07z"/><path fill="#EA4335" d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 001.83 5.4L4.5 7.49a4.77 4.77 0 014.48-3.3z"/></svg>\n    Continue with Google\n  </a>\n  <div class="divider">or</div>\n  <div class="err" id="err"></div>\n  <label>Email</label>\n  <input type="email" id="email" placeholder="you@company.com" autofocus>\n  <label>Password</label>\n  <input type="password" id="password" placeholder="Your password">\n  <button class="btn" onclick="doLogin()">Sign In</button>\n  <div class="link">No account? <a href="/signup">Sign up free</a> · <a href="/pricing">Pricing</a></div>\n</div>\n<script>\nconst params = new URLSearchParams(window.location.search);\nif (params.get(\'error\')) {\n  const err = document.getElementById(\'err\');\n  err.textContent = \'Google sign-in failed. Please try email/password or try again.\';\n  err.style.display = \'block\';\n}\nasync function doLogin() {\n  const email = document.getElementById(\'email\').value.trim();\n  const password = document.getElementById(\'password\').value;\n  const err = document.getElementById(\'err\');\n  err.style.display = \'none\';\n  try {\n    const r = await fetch(\'/api/v1/auth/login\', {\n      method: \'POST\', headers: {\'Content-Type\': \'application/json\'},\n      body: JSON.stringify({email, password})\n    });\n    const data = await r.json();\n    if (!r.ok) { err.textContent = data.detail || \'Login failed\'; err.style.display = \'block\'; return; }\n    localStorage.setItem(\'apex_token\', data.token);\n    localStorage.setItem(\'apex_key\', data.api_key);\n    localStorage.setItem(\'apex_email\', data.email);\n    window.location.href = \'/dashboard\';\n  } catch(e) { err.textContent = \'Network error — please try again\'; err.style.display = \'block\'; }\n}\ndocument.addEventListener(\'keydown\', e => { if(e.key === \'Enter\') doLogin(); });\n</script>\n</body></html>\n'
PRICING_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Pricing — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;padding:0 20px 80px}\nnav{display:flex;justify-content:space-between;align-items:center;padding:20px 0;max-width:1000px;margin:0 auto 48px;border-bottom:1px solid rgba(255,255,255,0.06)}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0}\nnav a{color:#888;text-decoration:none;font-size:14px;margin-left:20px}\nnav a:hover{color:#e8e8f0}\n.nav-cta{background:#00f0a0;color:#0a0a0f;padding:8px 18px;border-radius:8px;font-weight:700}\n.hero{text-align:center;max-width:1000px;margin:0 auto 60px}\n.badge{display:inline-block;background:rgba(0,240,160,0.1);border:1px solid rgba(0,240,160,0.2);color:#00f0a0;font-size:11px;padding:5px 14px;border-radius:20px;margin-bottom:16px;font-family:\'IBM Plex Mono\',monospace;letter-spacing:1px}\nh1{font-size:48px;font-weight:800;margin-bottom:14px;line-height:1.1}\n.sub{color:#888;font-size:18px;max-width:540px;margin:0 auto}\n.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:1000px;margin:0 auto 32px}\n@media(max-width:700px){.grid{grid-template-columns:1fr}}\n.tier{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:32px;position:relative;transition:border-color 0.2s}\n.tier:hover{border-color:rgba(255,255,255,0.15)}\n.tier.featured{border-color:#00f0a0;background:rgba(0,240,160,0.03)}\n.tier-badge{position:absolute;top:-14px;left:50%;transform:translateX(-50%);background:#00f0a0;color:#0a0a0f;font-size:10px;font-weight:700;padding:4px 14px;border-radius:20px;letter-spacing:1.5px;white-space:nowrap}\n.tier-name{font-size:20px;font-weight:700;margin-bottom:6px}\n.price{font-size:48px;font-weight:800;color:#00f0a0;line-height:1;margin:12px 0 4px}\n.price span{font-size:16px;color:#666;font-weight:400}\n.desc{color:#888;font-size:13px;margin-bottom:24px}\nul{list-style:none;margin-bottom:28px}\nli{padding:8px 0;font-size:14px;color:#aaa;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;align-items:center;gap:8px}\nli:last-child{border:none}\nli:before{content:"✓";color:#00f0a0;font-weight:700;flex-shrink:0}\n.btn{display:block;width:100%;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;text-align:center;text-decoration:none;font-family:\'Inter\',sans-serif;transition:opacity 0.2s}\n.btn:hover{opacity:0.9}\n.btn-mint{background:#00f0a0;color:#0a0a0f}\n.btn-outline{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#e8e8f0}\n.enterprise-bar{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:32px 40px;max-width:1000px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:20px}\n.faq{max-width:700px;margin:48px auto 0}\n.faq h2{font-size:28px;font-weight:800;margin-bottom:24px;text-align:center}\n.q{margin-bottom:20px;padding:20px;background:#13131a;border-radius:10px;border:1px solid rgba(255,255,255,0.06)}\n.q strong{display:block;margin-bottom:8px;font-size:15px}\n.q p{color:#888;font-size:14px;line-height:1.6}\n</style>\n</head>\n<body>\n<nav>\n  <div class="logo">APEX SWARM</div>\n  <div>\n    <a href="/demo">Live Demo</a>\n    <a href="/login">Sign In</a>\n    <a href="/signup" class="nav-cta">Get Started</a>\n  </div>\n</nav>\n<div class="hero">\n  <div class="badge">PRICING</div>\n  <h1>Your AI workforce.<br>Pay as you grow.</h1>\n  <p class="sub">Start free. Upgrade when your AI agents need to work harder.</p>\n</div>\n<div class="grid">\n  <div class="tier">\n    <div class="tier-name">Starter</div>\n    <div class="price">$49<span>/mo</span></div>\n    <div class="desc">For individuals and small teams</div>\n    <ul>\n      <li>25 agent runs per day</li>\n      <li>1 background worker (daemon)</li>\n      <li>3 scheduled tasks</li>\n      <li>Telegram alerts</li>\n      <li>All 66+ agent types</li>\n      <li>API access</li>\n    </ul>\n    <a href="/signup" class="btn btn-outline">Get Started</a>\n  </div>\n  <div class="tier featured">\n    <div class="tier-badge">MOST POPULAR</div>\n    <div class="tier-name">Pro</div>\n    <div class="price">$199<span>/mo</span></div>\n    <div class="desc">For growing teams that need more</div>\n    <ul>\n      <li>100 agent runs per day</li>\n      <li>5 background workers</li>\n      <li>10 scheduled tasks</li>\n      <li>Telegram + Slack alerts</li>\n      <li>Team access (5 seats)</li>\n      <li>Priority execution queue</li>\n      <li>Workflow automation</li>\n    </ul>\n    <a href="/signup" class="btn btn-mint">Start Free Trial</a>\n  </div>\n  <div class="tier">\n    <div class="tier-name">Enterprise</div>\n    <div class="price">$999<span>/mo</span></div>\n    <div class="desc">Unlimited AI workforce at scale</div>\n    <ul>\n      <li>Unlimited agent runs</li>\n      <li>50 background workers</li>\n      <li>Unlimited scheduled tasks</li>\n      <li>All output channels</li>\n      <li>Unlimited team seats</li>\n      <li>Audit logs + SSO</li>\n      <li>Dedicated support SLA</li>\n      <li>Custom agent training</li>\n    </ul>\n    <a href="mailto:sales@apexswarm.ai" class="btn btn-outline">Contact Sales</a>\n  </div>\n</div>\n<div class="enterprise-bar">\n  <div>\n    <div style="font-size:20px;font-weight:700;margin-bottom:6px">Need a custom plan?</div>\n    <div style="color:#888;font-size:14px">White-label, on-premise, custom agents, or volume pricing available.</div>\n  </div>\n  <a href="mailto:sales@apexswarm.ai" class="btn btn-mint" style="width:auto;padding:14px 32px">Talk to Sales</a>\n</div>\n<div class="faq">\n  <h2>Common questions</h2>\n  <div class="q"><strong>What\'s an agent run?</strong><p>Each time you deploy an agent to complete a task, that counts as one run. Background workers (daemons) use runs each time they cycle.</p></div>\n  <div class="q"><strong>What\'s a background worker?</strong><p>A daemon — an AI agent that runs continuously on a schedule, monitoring for conditions and firing alerts to Telegram or Slack when they\'re met.</p></div>\n  <div class="q"><strong>Can I cancel anytime?</strong><p>Yes. Cancel from your dashboard at any time. You keep access until the end of your billing period.</p></div>\n  <div class="q"><strong>Do you offer a free trial?</strong><p>Free accounts can run up to 5 agents per day. Upgrade anytime. No credit card required to start.</p></div>\n</div>\n</body></html>\n'
DEMO_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Live Demo — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\n:root{--bg:#0a0a0f;--bg2:#13131a;--mint:#00f0a0;--text:#e8e8f0;--text2:#aaa;--text3:#555;--border:rgba(255,255,255,0.08)}\nbody{background:var(--bg);color:var(--text);font-family:\'Inter\',sans-serif;min-height:100vh}\nnav{display:flex;justify-content:space-between;align-items:center;padding:18px 40px;border-bottom:1px solid var(--border)}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:var(--mint)}\nnav a{color:var(--text2);text-decoration:none;font-size:14px;margin-left:20px}\n.nav-cta{background:var(--mint);color:var(--bg);padding:8px 18px;border-radius:8px;font-weight:700;color:#0a0a0f!important}\n.hero{text-align:center;padding:56px 20px 40px;max-width:760px;margin:0 auto}\n.badge{display:inline-flex;align-items:center;gap:6px;background:rgba(0,240,160,0.08);border:1px solid rgba(0,240,160,0.2);color:var(--mint);font-size:11px;padding:5px 14px;border-radius:20px;margin-bottom:18px;font-family:\'IBM Plex Mono\',monospace;letter-spacing:1px}\n.dot{width:6px;height:6px;border-radius:50%;background:var(--mint);animation:pulse 2s infinite}\n@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}\nh1{font-size:44px;font-weight:800;margin-bottom:12px;line-height:1.1}\nh1 span{color:var(--mint)}\n.sub{color:var(--text2);font-size:17px;margin-bottom:40px}\n.demo-wrap{max-width:760px;margin:0 auto;padding:0 20px 60px}\n.card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;overflow:hidden;margin-bottom:20px}\n.card-head{padding:18px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}\n.card-title{font-weight:700;font-size:15px}\n.card-body{padding:24px}\n.agents{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:20px}\n@media(max-width:500px){.agents{grid-template-columns:repeat(2,1fr)}}\n.agent{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:11px;cursor:pointer;font-size:12px;text-align:center;transition:all 0.15s;color:var(--text2);line-height:1.3}\n.agent:hover,.agent.sel{border-color:var(--mint);color:var(--mint);background:rgba(0,240,160,0.05)}\n.step{display:flex;gap:14px;margin-bottom:18px}\n.step-n{width:30px;height:30px;border-radius:50%;background:rgba(0,240,160,0.1);border:1px solid var(--mint);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:var(--mint);flex-shrink:0;margin-top:2px}\n.step-title{font-weight:600;margin-bottom:3px;font-size:14px}\n.step-desc{font-size:12px;color:var(--text3)}\ninput{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px 14px;color:var(--text);font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-top:8px;transition:border-color 0.2s}\ninput:focus{border-color:var(--mint)}\n.btn{width:100%;background:var(--mint);color:var(--bg);border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;margin-top:16px;font-family:\'Inter\',sans-serif;transition:opacity 0.2s}\n.btn:disabled{opacity:0.4;cursor:not-allowed}\n.btn:hover:not(:disabled){opacity:0.9}\n.loading{display:none;text-align:center;padding:32px;color:var(--text3)}\n.spinner{width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--mint);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 12px}\n@keyframes spin{to{transform:rotate(360deg)}}\n.result{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:18px;margin-top:16px;font-size:13px;color:var(--text2);line-height:1.75;white-space:pre-wrap;word-break:break-word;display:none;max-height:400px;overflow-y:auto}\n.cta-bar{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:40px;text-align:center;max-width:760px;margin:0 auto 60px}\n.cta-bar h2{font-size:30px;font-weight:800;margin-bottom:10px}\n.cta-bar p{color:var(--text2);margin-bottom:24px}\n.cta-btn{display:inline-block;background:var(--mint);color:var(--bg);padding:16px 40px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:800;transition:opacity 0.2s}\n.cta-btn:hover{opacity:0.9}\n</style>\n</head>\n<body>\n<nav>\n  <div class="logo">APEX SWARM</div>\n  <div>\n    <div class="badge" style="display:inline-flex"><div class="dot"></div>Live</div>\n    <a href="/pricing">Pricing</a>\n    <a href="/signup" class="nav-cta">Get Started</a>\n  </div>\n</nav>\n<div class="hero">\n  <div class="badge"><div class="dot"></div>LIVE DEMO — NO SIGNUP REQUIRED</div>\n  <h1>Your AI workforce,<br><span>working right now</span></h1>\n  <p class="sub">Pick an agent. Give it a task. Watch real AI work in real time.</p>\n</div>\n<div class="demo-wrap">\n  <div class="card">\n    <div class="card-head">\n      <div class="card-title">⚡ Deploy an AI Agent</div>\n      <div class="badge" style="margin:0"><div class="dot"></div>Connected</div>\n    </div>\n    <div class="card-body">\n      <div class="step">\n        <div class="step-n">1</div>\n        <div>\n          <div class="step-title">Choose your agent</div>\n          <div class="step-desc">Pick the AI specialist for your task</div>\n          <div class="agents">\n            <div class="agent sel" onclick="sel(this,\'research\',\'Research Analyst\')">🔬 Research Analyst</div>\n            <div class="agent" onclick="sel(this,\'competitor-analyst\',\'Competitor Intel\')">🎯 Competitor Intel</div>\n            <div class="agent" onclick="sel(this,\'copywriter\',\'Copywriter\')">✍️ Copywriter</div>\n            <div class="agent" onclick="sel(this,\'financial-analyst\',\'Financial Analyst\')">📊 Financial Analyst</div>\n            <div class="agent" onclick="sel(this,\'social-media\',\'Social Media\')">📱 Social Media</div>\n            <div class="agent" onclick="sel(this,\'lead-qualifier\',\'Lead Qualifier\')">🏆 Lead Qualifier</div>\n          </div>\n        </div>\n      </div>\n      <div class="step">\n        <div class="step-n">2</div>\n        <div style="flex:1">\n          <div class="step-title">Give it a task</div>\n          <div class="step-desc">Be specific for better results</div>\n          <input type="text" id="taskInput" value="Analyze the competitive landscape for AI agent platforms in 2025 — who are the top players and what are their weaknesses?">\n        </div>\n      </div>\n      <div class="step">\n        <div class="step-n">3</div>\n        <div>\n          <div class="step-title">Watch it work</div>\n          <div class="step-desc">Real AI execution — no mock data, no pre-recorded responses</div>\n        </div>\n      </div>\n      <button class="btn" id="runBtn" onclick="runDemo()">⚡ Deploy Agent Now</button>\n      <div class="loading" id="loading">\n        <div class="spinner"></div>\n        <div id="loadingText" style="font-size:13px">Initializing agent...</div>\n      </div>\n      <div class="result" id="result"></div>\n    </div>\n  </div>\n</div>\n<div class="cta-bar">\n  <h2>Ready to scale this?</h2>\n  <p>Run 66+ agents 24/7. Get alerts on Slack and Telegram. Manage your whole AI workforce from one dashboard.</p>\n  <a href="/signup" class="cta-btn">Start Free — No Credit Card</a>\n  <div style="margin-top:14px;font-size:13px;color:var(--text3)">\n    <a href="/pricing" style="color:var(--mint)">See pricing</a> &nbsp;·&nbsp; <a href="/dashboard" style="color:var(--mint)">View dashboard</a>\n  </div>\n</div>\n<script>\nlet agentType = \'research\';\nconst tasks = {\n  \'research\': \'Analyze the competitive landscape for AI agent platforms in 2025 — who are the top players and what are their weaknesses?\',\n  \'competitor-analyst\': \'Compare Salesforce vs HubSpot CRM — key strengths, weaknesses, and which wins for mid-market B2B\',\n  \'copywriter\': \'Write 3 landing page headlines for an AI workforce platform targeting enterprise sales teams\',\n  \'financial-analyst\': \'Analyze Nvidia revenue growth trends and whether current valuation is justified\',\n  \'social-media\': \'Create 3 high-engagement LinkedIn posts announcing an AI workforce product launch\',\n  \'lead-qualifier\': \'Research Stripe as a potential enterprise customer for an AI tooling platform — score their fit\'\n};\nfunction sel(el, type, name) {\n  document.querySelectorAll(\'.agent\').forEach(a => a.classList.remove(\'sel\'));\n  el.classList.add(\'sel\');\n  agentType = type;\n  document.getElementById(\'taskInput\').value = tasks[type] || \'\';\n}\nasync function runDemo() {\n  const task = document.getElementById(\'taskInput\').value.trim();\n  if (!task) return;\n  const btn = document.getElementById(\'runBtn\');\n  const loading = document.getElementById(\'loading\');\n  const result = document.getElementById(\'result\');\n  const loadingText = document.getElementById(\'loadingText\');\n  btn.disabled = true;\n  loading.style.display = \'block\';\n  result.style.display = \'none\';\n  const msgs = [\'Initializing agent...\',\'Connecting to live tools...\',\'Researching and analyzing...\',\'Processing results...\',\'Almost done...\'];\n  let mi = 0;\n  const interval = setInterval(() => { loadingText.textContent = msgs[Math.min(mi++, msgs.length-1)]; }, 3500);\n  try {\n    const r = await fetch(\'/api/v1/deploy\', {\n      method: \'POST\', headers: {\'Content-Type\': \'application/json\', \'X-Api-Key\': \'dev-mode\'},\n      body: JSON.stringify({agent_type: agentType, task_description: task})\n    });\n    const data = await r.json();\n    clearInterval(interval);\n    if (data.agent_id) {\n      loadingText.textContent = \'Agent working...\';\n      let attempts = 0;\n      const poll = setInterval(async () => {\n        attempts++;\n        try {\n          const sr = await fetch(\'/api/v1/status/\' + data.agent_id, {headers: {\'X-Api-Key\': \'dev-mode\'}});\n          const sd = await sr.json();\n          if (sd.status === \'completed\' || sd.status === \'failed\' || attempts > 40) {\n            clearInterval(poll);\n            loading.style.display = \'none\';\n            result.style.display = \'block\';\n            result.textContent = sd.result || \'Agent completed. Open dashboard to see full results.\';\n            btn.disabled = false;\n          }\n        } catch(e) { if(attempts > 40) { clearInterval(poll); loading.style.display=\'none\'; btn.disabled=false; } }\n      }, 2000);\n    } else {\n      loading.style.display = \'none\';\n      result.style.display = \'block\';\n      result.textContent = JSON.stringify(data, null, 2);\n      btn.disabled = false;\n    }\n  } catch(e) {\n    clearInterval(interval);\n    loading.style.display = \'none\';\n    result.style.display = \'block\';\n    result.textContent = \'Error: \' + e.message;\n    btn.disabled = false;\n  }\n}\n</script>\n</body></html>\n'
ACCEPT_INVITE_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Accept Invite — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}\n.card{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:100%;max-width:440px}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0;text-transform:uppercase;margin-bottom:10px}\n.icon{font-size:48px;margin-bottom:16px;display:block;text-align:center}\nh1{font-size:24px;font-weight:800;margin-bottom:6px;text-align:center}\n.sub{color:#888;font-size:14px;margin-bottom:28px;text-align:center}\nlabel{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:6px}\ninput{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 14px;color:#e8e8f0;font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-bottom:18px;transition:border-color 0.2s}\ninput:focus{border-color:#00f0a0}\n.btn{width:100%;background:#00f0a0;color:#0a0a0f;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:\'Inter\',sans-serif;transition:opacity 0.2s}\n.btn:hover{opacity:0.9}\n.err{color:#ff4d6d;font-size:13px;margin-bottom:16px;display:none;padding:10px;background:rgba(255,77,109,0.1);border-radius:6px}\n.success{display:none;text-align:center;padding:20px;background:rgba(0,240,160,0.06);border:1px solid rgba(0,240,160,0.2);border-radius:10px;margin-top:16px}\n.success h3{color:#00f0a0;font-size:18px;margin-bottom:8px}\n.key{background:#0a0a0f;padding:8px 12px;border-radius:6px;font-family:\'IBM Plex Mono\',monospace;font-size:13px;color:#00f0a0;word-break:break-all;margin:10px 0}\n.go{display:block;margin-top:16px;background:#00f0a0;color:#0a0a0f;border-radius:8px;padding:12px;font-weight:700;text-decoration:none;text-align:center}\n</style>\n</head>\n<body>\n<div class="card">\n  <div class="logo">APEX SWARM</div>\n  <span class="icon">🤝</span>\n  <h1>You\'ve been invited</h1>\n  <p class="sub">Join your team\'s AI workforce platform</p>\n  <div class="err" id="err"></div>\n  <label>Your Email</label>\n  <input type="email" id="email" placeholder="your@email.com" autofocus>\n  <input type="hidden" id="token">\n  <button class="btn" onclick="acceptInvite()">Accept Invite & Join Team</button>\n  <div class="success" id="success">\n    <h3>Welcome to the team! 🎉</h3>\n    <p style="color:#aaa;font-size:13px;margin-bottom:8px">Your API Key (save this):</p>\n    <div class="key" id="apiKey"></div>\n    <a href="/dashboard" class="go">Open Dashboard →</a>\n  </div>\n</div>\n<script>\nconst params = new URLSearchParams(window.location.search);\ndocument.getElementById(\'token\').value = params.get(\'token\') || \'\';\nasync function acceptInvite() {\n  const email = document.getElementById(\'email\').value.trim();\n  const token = document.getElementById(\'token\').value;\n  const err = document.getElementById(\'err\');\n  err.style.display = \'none\';\n  if (!email) { err.textContent = \'Please enter your email\'; err.style.display = \'block\'; return; }\n  if (!token) { err.textContent = \'Invalid invite link\'; err.style.display = \'block\'; return; }\n  const r = await fetch(\'/api/v1/orgs/accept-invite\', {\n    method: \'POST\', headers: {\'Content-Type\': \'application/json\'},\n    body: JSON.stringify({token, email})\n  });\n  const data = await r.json();\n  if (!r.ok) { err.textContent = data.detail || \'Failed to accept invite\'; err.style.display = \'block\'; return; }\n  localStorage.setItem(\'apex_key\', data.api_key);\n  localStorage.setItem(\'apex_email\', email);\n  document.getElementById(\'apiKey\').textContent = data.api_key;\n  document.getElementById(\'success\').style.display = \'block\';\n  document.querySelector(\'.btn\').style.display = \'none\';\n}\n</script>\n</body></html>\n'


# ─── STATIC HTML PAGES ───────────────────────────────────
SIGNUP_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Sign Up — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}\n.card{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:100%;max-width:440px}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0;text-transform:uppercase;margin-bottom:10px}\nh1{font-size:26px;font-weight:800;margin-bottom:6px}\n.sub{color:#888;font-size:14px;margin-bottom:28px}\nlabel{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:6px}\ninput{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 14px;color:#e8e8f0;font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-bottom:18px;transition:border-color 0.2s}\ninput:focus{border-color:#00f0a0}\n.btn{display:block;width:100%;background:#00f0a0;color:#0a0a0f;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:\'Inter\',sans-serif;transition:opacity 0.2s;text-align:center;text-decoration:none;margin-bottom:12px}\n.btn:hover{opacity:0.9}\n.btn.outline{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#e8e8f0;display:flex;align-items:center;justify-content:center;gap:10px}\n.err{color:#ff4d6d;font-size:13px;margin-bottom:16px;display:none;padding:10px;background:rgba(255,77,109,0.1);border-radius:6px}\n.link{text-align:center;margin-top:16px;font-size:13px;color:#888}\n.link a{color:#00f0a0;text-decoration:none}\n.divider{display:flex;align-items:center;gap:12px;margin:16px 0;color:#555;font-size:12px}\n.divider:before,.divider:after{content:\'\';flex:1;height:1px;background:rgba(255,255,255,0.08)}\n.features{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}\n.feat{font-size:12px;color:#aaa;display:flex;align-items:center;gap:5px}\n.feat span{color:#00f0a0}\n</style>\n</head>\n<body>\n<div class="card">\n  <div class="logo">APEX SWARM</div>\n  <h1>Start your AI workforce</h1>\n  <p class="sub">Deploy 66+ autonomous AI agents in 60 seconds</p>\n  <div class="features">\n    <div class="feat"><span>✓</span> Free to start</div>\n    <div class="feat"><span>✓</span> No credit card</div>\n    <div class="feat"><span>✓</span> 24/7 workers</div>\n  </div>\n  <a href="/api/v1/auth/google" class="btn outline">\n    <svg width="18" height="18" viewBox="0 0 18 18"><path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 002.38-5.88c0-.57-.05-.66-.15-1.18z"/><path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2a4.8 4.8 0 01-7.18-2.54H1.83v2.07A8 8 0 008.98 17z"/><path fill="#FBBC05" d="M4.5 10.52a4.8 4.8 0 010-3.04V5.41H1.83a8 8 0 000 7.18l2.67-2.07z"/><path fill="#EA4335" d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 001.83 5.4L4.5 7.49a4.77 4.77 0 014.48-3.3z"/></svg>\n    Continue with Google\n  </a>\n  <div class="divider">or</div>\n  <div class="err" id="err"></div>\n  <label>Email</label>\n  <input type="email" id="email" placeholder="you@company.com" autofocus>\n  <label>Password</label>\n  <input type="password" id="password" placeholder="At least 8 characters">\n  <button class="btn" onclick="doSignup()">Create Free Account</button>\n  <div class="link">Already have an account? <a href="/login">Sign in</a> · <a href="/pricing">See pricing</a></div>\n</div>\n<script>\nasync function doSignup() {\n  const email = document.getElementById(\'email\').value.trim();\n  const password = document.getElementById(\'password\').value;\n  const err = document.getElementById(\'err\');\n  err.style.display = \'none\';\n  if (!email || !password) { err.textContent = \'Please fill in all fields\'; err.style.display = \'block\'; return; }\n  try {\n    const r = await fetch(\'/api/v1/auth/signup\', {\n      method: \'POST\', headers: {\'Content-Type\': \'application/json\'},\n      body: JSON.stringify({email, password})\n    });\n    const data = await r.json();\n    if (!r.ok) { err.textContent = data.detail || \'Signup failed\'; err.style.display = \'block\'; return; }\n    localStorage.setItem(\'apex_token\', data.token);\n    localStorage.setItem(\'apex_key\', data.api_key);\n    localStorage.setItem(\'apex_email\', data.email);\n    window.location.href = \'/dashboard\';\n  } catch(e) { err.textContent = \'Network error — please try again\'; err.style.display = \'block\'; }\n}\ndocument.addEventListener(\'keydown\', e => { if(e.key === \'Enter\') doSignup(); });\n</script>\n</body></html>\n'
LOGIN_HTML_NEW = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Sign In — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}\n.card{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:100%;max-width:440px}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0;text-transform:uppercase;margin-bottom:10px}\nh1{font-size:26px;font-weight:800;margin-bottom:6px}\n.sub{color:#888;font-size:14px;margin-bottom:28px}\nlabel{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:6px}\ninput{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 14px;color:#e8e8f0;font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-bottom:18px;transition:border-color 0.2s}\ninput:focus{border-color:#00f0a0}\n.btn{display:block;width:100%;background:#00f0a0;color:#0a0a0f;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:\'Inter\',sans-serif;transition:opacity 0.2s;text-align:center;text-decoration:none;margin-bottom:12px}\n.btn:hover{opacity:0.9}\n.btn.outline{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#e8e8f0;display:flex;align-items:center;justify-content:center;gap:10px}\n.err{color:#ff4d6d;font-size:13px;margin-bottom:16px;display:none;padding:10px;background:rgba(255,77,109,0.1);border-radius:6px}\n.link{text-align:center;margin-top:16px;font-size:13px;color:#888}\n.link a{color:#00f0a0;text-decoration:none}\n.divider{display:flex;align-items:center;gap:12px;margin:16px 0;color:#555;font-size:12px}\n.divider:before,.divider:after{content:\'\';flex:1;height:1px;background:rgba(255,255,255,0.08)}\n</style>\n</head>\n<body>\n<div class="card">\n  <div class="logo">APEX SWARM</div>\n  <h1>Welcome back</h1>\n  <p class="sub">Sign in to your AI workforce</p>\n  <a href="/api/v1/auth/google" class="btn outline">\n    <svg width="18" height="18" viewBox="0 0 18 18"><path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 002.38-5.88c0-.57-.05-.66-.15-1.18z"/><path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2a4.8 4.8 0 01-7.18-2.54H1.83v2.07A8 8 0 008.98 17z"/><path fill="#FBBC05" d="M4.5 10.52a4.8 4.8 0 010-3.04V5.41H1.83a8 8 0 000 7.18l2.67-2.07z"/><path fill="#EA4335" d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 001.83 5.4L4.5 7.49a4.77 4.77 0 014.48-3.3z"/></svg>\n    Continue with Google\n  </a>\n  <div class="divider">or</div>\n  <div class="err" id="err"></div>\n  <label>Email</label>\n  <input type="email" id="email" placeholder="you@company.com" autofocus>\n  <label>Password</label>\n  <input type="password" id="password" placeholder="Your password">\n  <button class="btn" onclick="doLogin()">Sign In</button>\n  <div class="link">No account? <a href="/signup">Sign up free</a> · <a href="/pricing">Pricing</a></div>\n</div>\n<script>\nconst params = new URLSearchParams(window.location.search);\nif (params.get(\'error\')) {\n  const err = document.getElementById(\'err\');\n  err.textContent = \'Google sign-in failed. Please try email/password or try again.\';\n  err.style.display = \'block\';\n}\nasync function doLogin() {\n  const email = document.getElementById(\'email\').value.trim();\n  const password = document.getElementById(\'password\').value;\n  const err = document.getElementById(\'err\');\n  err.style.display = \'none\';\n  try {\n    const r = await fetch(\'/api/v1/auth/login\', {\n      method: \'POST\', headers: {\'Content-Type\': \'application/json\'},\n      body: JSON.stringify({email, password})\n    });\n    const data = await r.json();\n    if (!r.ok) { err.textContent = data.detail || \'Login failed\'; err.style.display = \'block\'; return; }\n    localStorage.setItem(\'apex_token\', data.token);\n    localStorage.setItem(\'apex_key\', data.api_key);\n    localStorage.setItem(\'apex_email\', data.email);\n    window.location.href = \'/dashboard\';\n  } catch(e) { err.textContent = \'Network error — please try again\'; err.style.display = \'block\'; }\n}\ndocument.addEventListener(\'keydown\', e => { if(e.key === \'Enter\') doLogin(); });\n</script>\n</body></html>\n'
PRICING_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Pricing — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;padding:0 20px 80px}\nnav{display:flex;justify-content:space-between;align-items:center;padding:20px 0;max-width:1000px;margin:0 auto 48px;border-bottom:1px solid rgba(255,255,255,0.06)}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0}\nnav a{color:#888;text-decoration:none;font-size:14px;margin-left:20px}\nnav a:hover{color:#e8e8f0}\n.nav-cta{background:#00f0a0;color:#0a0a0f;padding:8px 18px;border-radius:8px;font-weight:700}\n.hero{text-align:center;max-width:1000px;margin:0 auto 60px}\n.badge{display:inline-block;background:rgba(0,240,160,0.1);border:1px solid rgba(0,240,160,0.2);color:#00f0a0;font-size:11px;padding:5px 14px;border-radius:20px;margin-bottom:16px;font-family:\'IBM Plex Mono\',monospace;letter-spacing:1px}\nh1{font-size:48px;font-weight:800;margin-bottom:14px;line-height:1.1}\n.sub{color:#888;font-size:18px;max-width:540px;margin:0 auto}\n.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:1000px;margin:0 auto 32px}\n@media(max-width:700px){.grid{grid-template-columns:1fr}}\n.tier{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:32px;position:relative;transition:border-color 0.2s}\n.tier:hover{border-color:rgba(255,255,255,0.15)}\n.tier.featured{border-color:#00f0a0;background:rgba(0,240,160,0.03)}\n.tier-badge{position:absolute;top:-14px;left:50%;transform:translateX(-50%);background:#00f0a0;color:#0a0a0f;font-size:10px;font-weight:700;padding:4px 14px;border-radius:20px;letter-spacing:1.5px;white-space:nowrap}\n.tier-name{font-size:20px;font-weight:700;margin-bottom:6px}\n.price{font-size:48px;font-weight:800;color:#00f0a0;line-height:1;margin:12px 0 4px}\n.price span{font-size:16px;color:#666;font-weight:400}\n.desc{color:#888;font-size:13px;margin-bottom:24px}\nul{list-style:none;margin-bottom:28px}\nli{padding:8px 0;font-size:14px;color:#aaa;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;align-items:center;gap:8px}\nli:last-child{border:none}\nli:before{content:"✓";color:#00f0a0;font-weight:700;flex-shrink:0}\n.btn{display:block;width:100%;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;text-align:center;text-decoration:none;font-family:\'Inter\',sans-serif;transition:opacity 0.2s}\n.btn:hover{opacity:0.9}\n.btn-mint{background:#00f0a0;color:#0a0a0f}\n.btn-outline{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#e8e8f0}\n.enterprise-bar{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:32px 40px;max-width:1000px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:20px}\n.faq{max-width:700px;margin:48px auto 0}\n.faq h2{font-size:28px;font-weight:800;margin-bottom:24px;text-align:center}\n.q{margin-bottom:20px;padding:20px;background:#13131a;border-radius:10px;border:1px solid rgba(255,255,255,0.06)}\n.q strong{display:block;margin-bottom:8px;font-size:15px}\n.q p{color:#888;font-size:14px;line-height:1.6}\n</style>\n</head>\n<body>\n<nav>\n  <div class="logo">APEX SWARM</div>\n  <div>\n    <a href="/demo">Live Demo</a>\n    <a href="/login">Sign In</a>\n    <a href="/signup" class="nav-cta">Get Started</a>\n  </div>\n</nav>\n<div class="hero">\n  <div class="badge">PRICING</div>\n  <h1>Your AI workforce.<br>Pay as you grow.</h1>\n  <p class="sub">Start free. Upgrade when your AI agents need to work harder.</p>\n</div>\n<div class="grid">\n  <div class="tier">\n    <div class="tier-name">Starter</div>\n    <div class="price">$49<span>/mo</span></div>\n    <div class="desc">For individuals and small teams</div>\n    <ul>\n      <li>25 agent runs per day</li>\n      <li>1 background worker (daemon)</li>\n      <li>3 scheduled tasks</li>\n      <li>Telegram alerts</li>\n      <li>All 66+ agent types</li>\n      <li>API access</li>\n    </ul>\n    <a href="/signup" class="btn btn-outline">Get Started</a>\n  </div>\n  <div class="tier featured">\n    <div class="tier-badge">MOST POPULAR</div>\n    <div class="tier-name">Pro</div>\n    <div class="price">$199<span>/mo</span></div>\n    <div class="desc">For growing teams that need more</div>\n    <ul>\n      <li>100 agent runs per day</li>\n      <li>5 background workers</li>\n      <li>10 scheduled tasks</li>\n      <li>Telegram + Slack alerts</li>\n      <li>Team access (5 seats)</li>\n      <li>Priority execution queue</li>\n      <li>Workflow automation</li>\n    </ul>\n    <a href="/signup" class="btn btn-mint">Start Free Trial</a>\n  </div>\n  <div class="tier">\n    <div class="tier-name">Enterprise</div>\n    <div class="price">$999<span>/mo</span></div>\n    <div class="desc">Unlimited AI workforce at scale</div>\n    <ul>\n      <li>Unlimited agent runs</li>\n      <li>50 background workers</li>\n      <li>Unlimited scheduled tasks</li>\n      <li>All output channels</li>\n      <li>Unlimited team seats</li>\n      <li>Audit logs + SSO</li>\n      <li>Dedicated support SLA</li>\n      <li>Custom agent training</li>\n    </ul>\n    <a href="mailto:sales@apexswarm.ai" class="btn btn-outline">Contact Sales</a>\n  </div>\n</div>\n<div class="enterprise-bar">\n  <div>\n    <div style="font-size:20px;font-weight:700;margin-bottom:6px">Need a custom plan?</div>\n    <div style="color:#888;font-size:14px">White-label, on-premise, custom agents, or volume pricing available.</div>\n  </div>\n  <a href="mailto:sales@apexswarm.ai" class="btn btn-mint" style="width:auto;padding:14px 32px">Talk to Sales</a>\n</div>\n<div class="faq">\n  <h2>Common questions</h2>\n  <div class="q"><strong>What\'s an agent run?</strong><p>Each time you deploy an agent to complete a task, that counts as one run. Background workers (daemons) use runs each time they cycle.</p></div>\n  <div class="q"><strong>What\'s a background worker?</strong><p>A daemon — an AI agent that runs continuously on a schedule, monitoring for conditions and firing alerts to Telegram or Slack when they\'re met.</p></div>\n  <div class="q"><strong>Can I cancel anytime?</strong><p>Yes. Cancel from your dashboard at any time. You keep access until the end of your billing period.</p></div>\n  <div class="q"><strong>Do you offer a free trial?</strong><p>Free accounts can run up to 5 agents per day. Upgrade anytime. No credit card required to start.</p></div>\n</div>\n</body></html>\n'
DEMO_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Live Demo — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\n:root{--bg:#0a0a0f;--bg2:#13131a;--mint:#00f0a0;--text:#e8e8f0;--text2:#aaa;--text3:#555;--border:rgba(255,255,255,0.08)}\nbody{background:var(--bg);color:var(--text);font-family:\'Inter\',sans-serif;min-height:100vh}\nnav{display:flex;justify-content:space-between;align-items:center;padding:18px 40px;border-bottom:1px solid var(--border)}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:var(--mint)}\nnav a{color:var(--text2);text-decoration:none;font-size:14px;margin-left:20px}\n.nav-cta{background:var(--mint);color:var(--bg);padding:8px 18px;border-radius:8px;font-weight:700;color:#0a0a0f!important}\n.hero{text-align:center;padding:56px 20px 40px;max-width:760px;margin:0 auto}\n.badge{display:inline-flex;align-items:center;gap:6px;background:rgba(0,240,160,0.08);border:1px solid rgba(0,240,160,0.2);color:var(--mint);font-size:11px;padding:5px 14px;border-radius:20px;margin-bottom:18px;font-family:\'IBM Plex Mono\',monospace;letter-spacing:1px}\n.dot{width:6px;height:6px;border-radius:50%;background:var(--mint);animation:pulse 2s infinite}\n@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}\nh1{font-size:44px;font-weight:800;margin-bottom:12px;line-height:1.1}\nh1 span{color:var(--mint)}\n.sub{color:var(--text2);font-size:17px;margin-bottom:40px}\n.demo-wrap{max-width:760px;margin:0 auto;padding:0 20px 60px}\n.card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;overflow:hidden;margin-bottom:20px}\n.card-head{padding:18px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}\n.card-title{font-weight:700;font-size:15px}\n.card-body{padding:24px}\n.agents{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:20px}\n@media(max-width:500px){.agents{grid-template-columns:repeat(2,1fr)}}\n.agent{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:11px;cursor:pointer;font-size:12px;text-align:center;transition:all 0.15s;color:var(--text2);line-height:1.3}\n.agent:hover,.agent.sel{border-color:var(--mint);color:var(--mint);background:rgba(0,240,160,0.05)}\n.step{display:flex;gap:14px;margin-bottom:18px}\n.step-n{width:30px;height:30px;border-radius:50%;background:rgba(0,240,160,0.1);border:1px solid var(--mint);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:var(--mint);flex-shrink:0;margin-top:2px}\n.step-title{font-weight:600;margin-bottom:3px;font-size:14px}\n.step-desc{font-size:12px;color:var(--text3)}\ninput{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px 14px;color:var(--text);font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-top:8px;transition:border-color 0.2s}\ninput:focus{border-color:var(--mint)}\n.btn{width:100%;background:var(--mint);color:var(--bg);border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;margin-top:16px;font-family:\'Inter\',sans-serif;transition:opacity 0.2s}\n.btn:disabled{opacity:0.4;cursor:not-allowed}\n.btn:hover:not(:disabled){opacity:0.9}\n.loading{display:none;text-align:center;padding:32px;color:var(--text3)}\n.spinner{width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--mint);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 12px}\n@keyframes spin{to{transform:rotate(360deg)}}\n.result{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:18px;margin-top:16px;font-size:13px;color:var(--text2);line-height:1.75;white-space:pre-wrap;word-break:break-word;display:none;max-height:400px;overflow-y:auto}\n.cta-bar{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:40px;text-align:center;max-width:760px;margin:0 auto 60px}\n.cta-bar h2{font-size:30px;font-weight:800;margin-bottom:10px}\n.cta-bar p{color:var(--text2);margin-bottom:24px}\n.cta-btn{display:inline-block;background:var(--mint);color:var(--bg);padding:16px 40px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:800;transition:opacity 0.2s}\n.cta-btn:hover{opacity:0.9}\n</style>\n</head>\n<body>\n<nav>\n  <div class="logo">APEX SWARM</div>\n  <div>\n    <div class="badge" style="display:inline-flex"><div class="dot"></div>Live</div>\n    <a href="/pricing">Pricing</a>\n    <a href="/signup" class="nav-cta">Get Started</a>\n  </div>\n</nav>\n<div class="hero">\n  <div class="badge"><div class="dot"></div>LIVE DEMO — NO SIGNUP REQUIRED</div>\n  <h1>Your AI workforce,<br><span>working right now</span></h1>\n  <p class="sub">Pick an agent. Give it a task. Watch real AI work in real time.</p>\n</div>\n<div class="demo-wrap">\n  <div class="card">\n    <div class="card-head">\n      <div class="card-title">⚡ Deploy an AI Agent</div>\n      <div class="badge" style="margin:0"><div class="dot"></div>Connected</div>\n    </div>\n    <div class="card-body">\n      <div class="step">\n        <div class="step-n">1</div>\n        <div>\n          <div class="step-title">Choose your agent</div>\n          <div class="step-desc">Pick the AI specialist for your task</div>\n          <div class="agents">\n            <div class="agent sel" onclick="sel(this,\'research\',\'Research Analyst\')">🔬 Research Analyst</div>\n            <div class="agent" onclick="sel(this,\'competitor-analyst\',\'Competitor Intel\')">🎯 Competitor Intel</div>\n            <div class="agent" onclick="sel(this,\'copywriter\',\'Copywriter\')">✍️ Copywriter</div>\n            <div class="agent" onclick="sel(this,\'financial-analyst\',\'Financial Analyst\')">📊 Financial Analyst</div>\n            <div class="agent" onclick="sel(this,\'social-media\',\'Social Media\')">📱 Social Media</div>\n            <div class="agent" onclick="sel(this,\'lead-qualifier\',\'Lead Qualifier\')">🏆 Lead Qualifier</div>\n          </div>\n        </div>\n      </div>\n      <div class="step">\n        <div class="step-n">2</div>\n        <div style="flex:1">\n          <div class="step-title">Give it a task</div>\n          <div class="step-desc">Be specific for better results</div>\n          <input type="text" id="taskInput" value="Analyze the competitive landscape for AI agent platforms in 2025 — who are the top players and what are their weaknesses?">\n        </div>\n      </div>\n      <div class="step">\n        <div class="step-n">3</div>\n        <div>\n          <div class="step-title">Watch it work</div>\n          <div class="step-desc">Real AI execution — no mock data, no pre-recorded responses</div>\n        </div>\n      </div>\n      <button class="btn" id="runBtn" onclick="runDemo()">⚡ Deploy Agent Now</button>\n      <div class="loading" id="loading">\n        <div class="spinner"></div>\n        <div id="loadingText" style="font-size:13px">Initializing agent...</div>\n      </div>\n      <div class="result" id="result"></div>\n    </div>\n  </div>\n</div>\n<div class="cta-bar">\n  <h2>Ready to scale this?</h2>\n  <p>Run 66+ agents 24/7. Get alerts on Slack and Telegram. Manage your whole AI workforce from one dashboard.</p>\n  <a href="/signup" class="cta-btn">Start Free — No Credit Card</a>\n  <div style="margin-top:14px;font-size:13px;color:var(--text3)">\n    <a href="/pricing" style="color:var(--mint)">See pricing</a> &nbsp;·&nbsp; <a href="/dashboard" style="color:var(--mint)">View dashboard</a>\n  </div>\n</div>\n<script>\nlet agentType = \'research\';\nconst tasks = {\n  \'research\': \'Analyze the competitive landscape for AI agent platforms in 2025 — who are the top players and what are their weaknesses?\',\n  \'competitor-analyst\': \'Compare Salesforce vs HubSpot CRM — key strengths, weaknesses, and which wins for mid-market B2B\',\n  \'copywriter\': \'Write 3 landing page headlines for an AI workforce platform targeting enterprise sales teams\',\n  \'financial-analyst\': \'Analyze Nvidia revenue growth trends and whether current valuation is justified\',\n  \'social-media\': \'Create 3 high-engagement LinkedIn posts announcing an AI workforce product launch\',\n  \'lead-qualifier\': \'Research Stripe as a potential enterprise customer for an AI tooling platform — score their fit\'\n};\nfunction sel(el, type, name) {\n  document.querySelectorAll(\'.agent\').forEach(a => a.classList.remove(\'sel\'));\n  el.classList.add(\'sel\');\n  agentType = type;\n  document.getElementById(\'taskInput\').value = tasks[type] || \'\';\n}\nasync function runDemo() {\n  const task = document.getElementById(\'taskInput\').value.trim();\n  if (!task) return;\n  const btn = document.getElementById(\'runBtn\');\n  const loading = document.getElementById(\'loading\');\n  const result = document.getElementById(\'result\');\n  const loadingText = document.getElementById(\'loadingText\');\n  btn.disabled = true;\n  loading.style.display = \'block\';\n  result.style.display = \'none\';\n  const msgs = [\'Initializing agent...\',\'Connecting to live tools...\',\'Researching and analyzing...\',\'Processing results...\',\'Almost done...\'];\n  let mi = 0;\n  const interval = setInterval(() => { loadingText.textContent = msgs[Math.min(mi++, msgs.length-1)]; }, 3500);\n  try {\n    const r = await fetch(\'/api/v1/deploy\', {\n      method: \'POST\', headers: {\'Content-Type\': \'application/json\', \'X-Api-Key\': \'dev-mode\'},\n      body: JSON.stringify({agent_type: agentType, task_description: task})\n    });\n    const data = await r.json();\n    clearInterval(interval);\n    if (data.agent_id) {\n      loadingText.textContent = \'Agent working...\';\n      let attempts = 0;\n      const poll = setInterval(async () => {\n        attempts++;\n        try {\n          const sr = await fetch(\'/api/v1/status/\' + data.agent_id, {headers: {\'X-Api-Key\': \'dev-mode\'}});\n          const sd = await sr.json();\n          if (sd.status === \'completed\' || sd.status === \'failed\' || attempts > 40) {\n            clearInterval(poll);\n            loading.style.display = \'none\';\n            result.style.display = \'block\';\n            result.textContent = sd.result || \'Agent completed. Open dashboard to see full results.\';\n            btn.disabled = false;\n          }\n        } catch(e) { if(attempts > 40) { clearInterval(poll); loading.style.display=\'none\'; btn.disabled=false; } }\n      }, 2000);\n    } else {\n      loading.style.display = \'none\';\n      result.style.display = \'block\';\n      result.textContent = JSON.stringify(data, null, 2);\n      btn.disabled = false;\n    }\n  } catch(e) {\n    clearInterval(interval);\n    loading.style.display = \'none\';\n    result.style.display = \'block\';\n    result.textContent = \'Error: \' + e.message;\n    btn.disabled = false;\n  }\n}\n</script>\n</body></html>\n'
ACCEPT_INVITE_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Accept Invite — APEX SWARM</title>\n<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{background:#0a0a0f;color:#e8e8f0;font-family:\'Inter\',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}\n.card{background:#13131a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:100%;max-width:440px}\n.logo{font-family:\'IBM Plex Mono\',monospace;font-size:12px;letter-spacing:3px;color:#00f0a0;text-transform:uppercase;margin-bottom:10px}\n.icon{font-size:48px;margin-bottom:16px;display:block;text-align:center}\nh1{font-size:24px;font-weight:800;margin-bottom:6px;text-align:center}\n.sub{color:#888;font-size:14px;margin-bottom:28px;text-align:center}\nlabel{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:6px}\ninput{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 14px;color:#e8e8f0;font-size:14px;font-family:\'Inter\',sans-serif;outline:none;margin-bottom:18px;transition:border-color 0.2s}\ninput:focus{border-color:#00f0a0}\n.btn{width:100%;background:#00f0a0;color:#0a0a0f;border:none;border-radius:8px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:\'Inter\',sans-serif;transition:opacity 0.2s}\n.btn:hover{opacity:0.9}\n.err{color:#ff4d6d;font-size:13px;margin-bottom:16px;display:none;padding:10px;background:rgba(255,77,109,0.1);border-radius:6px}\n.success{display:none;text-align:center;padding:20px;background:rgba(0,240,160,0.06);border:1px solid rgba(0,240,160,0.2);border-radius:10px;margin-top:16px}\n.success h3{color:#00f0a0;font-size:18px;margin-bottom:8px}\n.key{background:#0a0a0f;padding:8px 12px;border-radius:6px;font-family:\'IBM Plex Mono\',monospace;font-size:13px;color:#00f0a0;word-break:break-all;margin:10px 0}\n.go{display:block;margin-top:16px;background:#00f0a0;color:#0a0a0f;border-radius:8px;padding:12px;font-weight:700;text-decoration:none;text-align:center}\n</style>\n</head>\n<body>\n<div class="card">\n  <div class="logo">APEX SWARM</div>\n  <span class="icon">🤝</span>\n  <h1>You\'ve been invited</h1>\n  <p class="sub">Join your team\'s AI workforce platform</p>\n  <div class="err" id="err"></div>\n  <label>Your Email</label>\n  <input type="email" id="email" placeholder="your@email.com" autofocus>\n  <input type="hidden" id="token">\n  <button class="btn" onclick="acceptInvite()">Accept Invite & Join Team</button>\n  <div class="success" id="success">\n    <h3>Welcome to the team! 🎉</h3>\n    <p style="color:#aaa;font-size:13px;margin-bottom:8px">Your API Key (save this):</p>\n    <div class="key" id="apiKey"></div>\n    <a href="/dashboard" class="go">Open Dashboard →</a>\n  </div>\n</div>\n<script>\nconst params = new URLSearchParams(window.location.search);\ndocument.getElementById(\'token\').value = params.get(\'token\') || \'\';\nasync function acceptInvite() {\n  const email = document.getElementById(\'email\').value.trim();\n  const token = document.getElementById(\'token\').value;\n  const err = document.getElementById(\'err\');\n  err.style.display = \'none\';\n  if (!email) { err.textContent = \'Please enter your email\'; err.style.display = \'block\'; return; }\n  if (!token) { err.textContent = \'Invalid invite link\'; err.style.display = \'block\'; return; }\n  const r = await fetch(\'/api/v1/orgs/accept-invite\', {\n    method: \'POST\', headers: {\'Content-Type\': \'application/json\'},\n    body: JSON.stringify({token, email})\n  });\n  const data = await r.json();\n  if (!r.ok) { err.textContent = data.detail || \'Failed to accept invite\'; err.style.display = \'block\'; return; }\n  localStorage.setItem(\'apex_key\', data.api_key);\n  localStorage.setItem(\'apex_email\', email);\n  document.getElementById(\'apiKey\').textContent = data.api_key;\n  document.getElementById(\'success\').style.display = \'block\';\n  document.querySelector(\'.btn\').style.display = \'none\';\n}\n</script>\n</body></html>\n'

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(): return HTMLResponse(SIGNUP_HTML)

@app.get("/login", response_class=HTMLResponse)
async def login_page_new(): return HTMLResponse(LOGIN_HTML_NEW)

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(): return HTMLResponse(PRICING_HTML)

@app.get("/demo", response_class=HTMLResponse)
async def demo_page(): return HTMLResponse(DEMO_HTML)

@app.get("/accept-invite", response_class=HTMLResponse)
async def accept_invite_page(): return HTMLResponse(ACCEPT_INVITE_HTML)

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(): return HTMLResponse(SIGNUP_HTML)

@app.get("/login", response_class=HTMLResponse)
async def login_page_new(): return HTMLResponse(LOGIN_HTML_NEW)

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(): return HTMLResponse(PRICING_HTML)

@app.get("/demo", response_class=HTMLResponse)
async def demo_page(): return HTMLResponse(DEMO_HTML)

@app.get("/accept-invite", response_class=HTMLResponse)
async def accept_invite_page(): return HTMLResponse(ACCEPT_INVITE_HTML)

@app.get("/", response_class=HTMLResponse)
async def landing_page():
    return HTMLResponse(LANDING_HTML)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML.replace("__VERSION__", VERSION))



LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX SWARM — Autonomous AI Workforce</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300&family=IBM+Plex+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#04040a;--bg2:#080810;--bg3:#0e0e1a;--mint:#00ffaa;--mint2:#00cc88;--mintglow:rgba(0,255,170,0.12);--text:#f0f0f8;--text2:#7878a0;--text3:#2e2e4a;--border:rgba(255,255,255,0.05);--rose:#ff3366;--amber:#ffaa00;--violet:#8855ff}
html{scroll-behavior:auto}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;overflow-x:hidden;cursor:none}
#cursor{position:fixed;width:8px;height:8px;background:var(--mint);border-radius:50%;pointer-events:none;z-index:9999;transform:translate(-50%,-50%);transition:width .3s,height .3s;mix-blend-mode:difference}
#cursor-follower{position:fixed;width:32px;height:32px;border:1px solid rgba(0,255,170,0.4);border-radius:50%;pointer-events:none;z-index:9998;transform:translate(-50%,-50%)}
#particle-canvas{position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.5}
nav{position:fixed;top:0;left:0;right:0;z-index:500;display:flex;align-items:center;justify-content:space-between;padding:24px 64px;transition:all .4s}
nav.scrolled{background:rgba(4,4,10,0.92);backdrop-filter:blur(24px);border-bottom:1px solid var(--border);padding:16px 64px}
.nav-logo{font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:4px;color:var(--mint);text-decoration:none}
.nav-center{display:flex;gap:36px}
.nav-center a{color:var(--text2);text-decoration:none;font-size:13px;transition:color .2s;position:relative}
.nav-center a::after{content:'';position:absolute;bottom:-2px;left:0;width:0;height:1px;background:var(--mint);transition:width .3s}
.nav-center a:hover{color:var(--text)}.nav-center a:hover::after{width:100%}
.nav-right{display:flex;gap:12px;align-items:center}
.btn-ghost{color:var(--text2);text-decoration:none;font-size:13px;font-weight:500;padding:9px 20px;border:1px solid var(--border);border-radius:6px;transition:all .2s}
.btn-ghost:hover{border-color:var(--text3);color:var(--text)}
.btn-mint{color:#04040a;background:var(--mint);text-decoration:none;font-size:13px;font-weight:600;padding:9px 20px;border-radius:6px;transition:all .25s}
.btn-mint:hover{background:var(--mint2);box-shadow:0 0 24px rgba(0,255,170,0.3)}
.hero{position:relative;z-index:1;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:120px 64px 80px;text-align:center;overflow:hidden}
.hero-eyebrow{display:inline-flex;align-items:center;gap:10px;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:3px;color:var(--mint);text-transform:uppercase;margin-bottom:40px;opacity:0;border:1px solid rgba(0,255,170,0.2);background:rgba(0,255,170,0.05);padding:8px 20px;border-radius:100px}
.eyebrow-dot{width:5px;height:5px;border-radius:50%;background:var(--mint);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.hero-title{font-family:'Bebas Neue',sans-serif;font-size:clamp(80px,12vw,180px);line-height:.88;letter-spacing:-2px;margin-bottom:32px}
.hero-title .line{overflow:hidden;display:block}
.hero-title .word{display:inline-block;transform:translateY(110%);opacity:0}
.hero-title .accent{color:transparent;-webkit-text-stroke:1.5px var(--mint);filter:drop-shadow(0 0 20px rgba(0,255,170,0.3))}
.hero-sub{font-size:clamp(15px,2vw,20px);color:var(--text2);font-weight:300;max-width:560px;line-height:1.8;margin-bottom:52px;opacity:0}
.hero-cta{display:flex;gap:14px;justify-content:center;opacity:0}
.cta-primary{display:inline-flex;align-items:center;gap:10px;background:var(--mint);color:#04040a;padding:16px 36px;border-radius:8px;font-weight:600;font-size:15px;text-decoration:none;transition:all .3s;position:relative;overflow:hidden}
.cta-primary::before{content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.2),transparent);transform:translateX(-100%);transition:transform .5s}
.cta-primary:hover::before{transform:translateX(100%)}
.cta-primary:hover{box-shadow:0 0 40px rgba(0,255,170,0.4);transform:translateY(-2px)}
.cta-secondary{display:inline-flex;align-items:center;gap:10px;border:1px solid rgba(255,255,255,0.1);color:var(--text2);padding:16px 36px;border-radius:8px;font-weight:500;font-size:15px;text-decoration:none;transition:all .3s}
.cta-secondary:hover{border-color:rgba(255,255,255,0.2);color:var(--text)}
.hero-metrics{position:absolute;bottom:48px;display:flex;gap:64px;opacity:0;font-family:'IBM Plex Mono',monospace}
.metric-val{font-size:32px;font-weight:700;color:var(--mint);letter-spacing:-1px}
.metric-label{font-size:10px;color:var(--text3);letter-spacing:2px;text-transform:uppercase;margin-top:4px}
.marquee-wrap{position:relative;z-index:1;border-top:1px solid var(--border);border-bottom:1px solid var(--border);background:var(--bg2);padding:16px 0;overflow:hidden;display:flex}
.marquee-track{display:flex;animation:marquee 25s linear infinite;white-space:nowrap;flex-shrink:0}
.marquee-wrap:hover .marquee-track{animation-play-state:paused}
.marquee-item{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:2px;color:var(--text3);text-transform:uppercase;padding:0 48px;border-right:1px solid var(--border);display:flex;align-items:center;gap:12px}
.marquee-item .dot{width:5px;height:5px;border-radius:50%;background:var(--mint);flex-shrink:0}
@keyframes marquee{to{transform:translateX(-50%)}}
section{position:relative;z-index:1}
.container{max-width:1200px;margin:0 auto;padding:0 64px}
.s-label{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:3px;color:var(--mint);text-transform:uppercase;margin-bottom:24px;display:flex;align-items:center;gap:12px}
.s-label::before{content:'';width:24px;height:1px;background:var(--mint)}
.s-title{font-family:'Bebas Neue',sans-serif;font-size:clamp(48px,6vw,80px);line-height:.95;letter-spacing:-1px;margin-bottom:24px}
.bento{padding:120px 0;background:var(--bg)}
.bento-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:2px;margin-top:64px;border-radius:16px;overflow:hidden;border:1px solid var(--border)}
.bento-card{background:var(--bg2);padding:36px;position:relative;overflow:hidden;transition:background .3s}
.bento-card::before{content:'';position:absolute;inset:0;background:radial-gradient(circle at var(--mx,50%) var(--my,50%),var(--mintglow),transparent 60%);opacity:0;transition:opacity .3s}
.bento-card:hover{background:var(--bg3)}.bento-card:hover::before{opacity:1}
.bc-1{grid-column:span 8;grid-row:span 2}.bc-2,.bc-3{grid-column:span 4}.bc-4,.bc-5{grid-column:span 4}.bc-6,.bc-7{grid-column:span 4}
.bento-icon{font-size:32px;margin-bottom:20px;display:block}
.bento-title{font-size:20px;font-weight:600;margin-bottom:10px;letter-spacing:-.3px}
.bento-desc{font-size:13px;color:var(--text3);line-height:1.7}
.bento-tag{display:inline-block;margin-top:14px;font-family:'IBM Plex Mono',monospace;font-size:9px;padding:4px 10px;letter-spacing:1px;background:var(--mintglow);color:var(--mint);border:1px solid rgba(0,255,170,0.15);border-radius:4px}
.bento-big-num{font-family:'Bebas Neue',sans-serif;font-size:96px;line-height:1;color:var(--mint);margin-bottom:16px;letter-spacing:-3px}
.bento-terminal{margin-top:24px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px;font-family:'IBM Plex Mono',monospace;font-size:11px;line-height:1.9}
.bt-green{color:var(--mint)}.bt-amber{color:var(--amber)}.bt-dim{color:var(--text3)}
.features-scroll{padding:160px 0;background:var(--bg2)}
.features-sticky{display:grid;grid-template-columns:1fr 1fr;gap:80px;align-items:start}
.sticky-left{position:sticky;top:100px}
.feature-item{padding:28px 0;border-bottom:1px solid var(--border);opacity:.3;transition:opacity .4s;cursor:default}
.feature-item.active{opacity:1}
.feature-num{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--mint);letter-spacing:2px;margin-bottom:8px}
.feature-title{font-size:18px;font-weight:600;margin-bottom:8px;letter-spacing:-.2px}
.feature-desc{font-size:13px;color:var(--text3);line-height:1.7}
.feature-visual{border-radius:12px;overflow:hidden;border:1px solid var(--border);background:var(--bg3);opacity:0;transform:translateY(32px);transition:all .5s;display:none}
.feature-visual.show{opacity:1;transform:translateY(0);display:block}
.fv-head{display:flex;align-items:center;gap:8px;padding:14px 18px;border-bottom:1px solid var(--border);background:rgba(255,255,255,.02)}
.fv-dot{width:8px;height:8px;border-radius:50%}
.fv-body{padding:24px;font-family:'IBM Plex Mono',monospace;font-size:12px;line-height:2}
.fv-tag{font-size:9px;margin-left:auto;letter-spacing:2px;color:var(--text3)}
.agents{padding:160px 0;background:var(--bg)}
.agent-scroll{display:flex;gap:16px;overflow-x:auto;scrollbar-width:none;padding:4px 64px 20px;margin:60px -64px 0;scroll-snap-type:x mandatory}
.agent-scroll::-webkit-scrollbar{display:none}
.agent-pill{flex-shrink:0;background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:24px 28px;min-width:220px;scroll-snap-align:start;transition:all .3s;cursor:default;position:relative;overflow:hidden}
.agent-pill::after{content:'';position:absolute;bottom:0;left:0;right:0;height:2px;background:var(--mint);transform:scaleX(0);transform-origin:left;transition:transform .3s}
.agent-pill:hover{border-color:rgba(0,255,170,0.2);transform:translateY(-4px);box-shadow:0 16px 48px rgba(0,0,0,.4)}
.agent-pill:hover::after{transform:scaleX(1)}
.agent-pill-icon{font-size:28px;margin-bottom:14px}.agent-pill-name{font-size:14px;font-weight:600;margin-bottom:6px}
.agent-pill-desc{font-size:12px;color:var(--text3);line-height:1.5}
.agent-pill-cat{margin-top:14px;font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--mint);letter-spacing:1.5px;text-transform:uppercase}
.pricing{padding:160px 0;background:var(--bg2)}
.pricing-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin-top:64px;border:1px solid var(--border);border-radius:16px;overflow:hidden}
.pc{background:var(--bg3);padding:44px;position:relative;transition:background .3s}
.pc:hover{background:var(--bg2)}.pc.featured{background:linear-gradient(160deg,rgba(0,255,170,0.07),var(--bg3))}
.pc-badge{position:absolute;top:20px;right:20px;background:var(--mint);color:#04040a;font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:700;padding:4px 12px;border-radius:100px;letter-spacing:2px}
.pc-tier{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:3px;color:var(--text3);text-transform:uppercase;margin-bottom:28px}
.pc-price{font-family:'Bebas Neue',sans-serif;font-size:72px;line-height:1;letter-spacing:-2px;color:var(--text);margin-bottom:4px}
.pc-price sup{font-size:28px;vertical-align:super;letter-spacing:0}
.pc-price sub{font-size:18px;vertical-align:baseline;color:var(--text3);letter-spacing:0}
.pc-desc{font-size:13px;color:var(--text3);margin-bottom:36px;line-height:1.6}
.pc-divider{height:1px;background:var(--border);margin-bottom:28px}
.pc-features{list-style:none;margin-bottom:36px}
.pc-features li{font-size:13px;color:var(--text2);padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;align-items:center;gap:10px}
.pc-features li:last-child{border:none}
.pc-features li::before{content:'';width:4px;height:4px;border-radius:50%;background:var(--mint);flex-shrink:0}
.pc-btn{display:block;width:100%;padding:14px;border-radius:8px;font-weight:600;font-size:14px;text-align:center;text-decoration:none;transition:all .3s;font-family:'DM Sans',sans-serif}
.pc-btn.outline{border:1px solid var(--border);color:var(--text2);background:transparent}
.pc-btn.outline:hover{border-color:var(--text3);color:var(--text)}
.pc-btn.filled{background:var(--mint);color:#04040a}
.pc-btn.filled:hover{background:var(--mint2);box-shadow:0 8px 32px rgba(0,255,170,0.25)}
.final-cta{padding:200px 64px;text-align:center;background:var(--bg);border-top:1px solid var(--border);position:relative;overflow:hidden}
.final-cta::before{content:'';position:absolute;bottom:-200px;left:50%;transform:translateX(-50%);width:800px;height:400px;background:radial-gradient(ellipse,rgba(0,255,170,0.08),transparent 70%);pointer-events:none}
.final-cta h2{font-family:'Bebas Neue',sans-serif;font-size:clamp(60px,10vw,140px);line-height:.9;letter-spacing:-3px;margin-bottom:32px}
.final-cta h2 span{color:var(--mint)}
.final-cta p{font-size:18px;color:var(--text2);max-width:480px;margin:0 auto 48px;line-height:1.7}
footer{padding:48px 64px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--text3);background:var(--bg);position:relative;z-index:1}
.footer-logo{font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:3px;color:var(--text3)}
.footer-links{display:flex;gap:28px}
.footer-links a{color:var(--text3);text-decoration:none;transition:color .2s}
.footer-links a:hover{color:var(--text2)}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--text3)}
@media(max-width:900px){nav{padding:18px 24px}.nav-center{display:none}.hero{padding:100px 24px 80px}.hero-metrics{display:none}.container{padding:0 24px}.bento-grid{grid-template-columns:1fr}.bc-1,.bc-2,.bc-3,.bc-4,.bc-5,.bc-6,.bc-7{grid-column:span 1;grid-row:span 1}.features-sticky{grid-template-columns:1fr}.sticky-left{position:relative;top:0}.agent-scroll{padding:4px 24px 20px;margin:40px -24px 0}.pricing-grid{grid-template-columns:1fr}footer{flex-direction:column;gap:16px;text-align:center;padding:32px 24px}}
</style>
</head>
<body>
<canvas id="particle-canvas"></canvas>
<div id="cursor"></div>
<div id="cursor-follower"></div>
<nav id="nav">
  <a href="/" class="nav-logo">APEX SWARM</a>
  <div class="nav-center">
    <a href="#features">Features</a>
    <a href="#agents">Agents</a>
    <a href="#pricing">Pricing</a>
    <a href="/demo">Demo</a>
  </div>
  <div class="nav-right">
    <a href="/login" class="btn-ghost">Sign In</a>
    <a href="/signup" class="btn-mint">Deploy Free</a>
  </div>
</nav>
<section class="hero" id="hero">
  <div class="hero-eyebrow"><div class="eyebrow-dot"></div>66+ Autonomous AI Agents &middot; Always On</div>
  <h1 class="hero-title">
    <span class="line"><span class="word">YOUR</span> <span class="word accent">AI</span></span>
    <span class="line"><span class="word">WORKFORCE</span></span>
    <span class="line"><span class="word accent">NEVER</span> <span class="word">SLEEPS</span></span>
  </h1>
  <p class="hero-sub">Deploy specialized AI agents that research, monitor, write, and analyze &mdash; 24/7 &mdash; alerting your team the moment something matters.</p>
  <div class="hero-cta">
    <a href="/signup" class="cta-primary">Start Deploying Free &rarr;</a>
    <a href="/demo" class="cta-secondary">Watch Live Demo</a>
  </div>
  <div class="hero-metrics">
    <div><div class="metric-val">66+</div><div class="metric-label">Specialists</div></div>
    <div style="width:1px;height:40px;background:var(--border)"></div>
    <div><div class="metric-val">24/7</div><div class="metric-label">Always On</div></div>
    <div style="width:1px;height:40px;background:var(--border)"></div>
    <div><div class="metric-val">60s</div><div class="metric-label">To Deploy</div></div>
    <div style="width:1px;height:40px;background:var(--border)"></div>
    <div><div class="metric-val">&#8734;</div><div class="metric-label">Scale</div></div>
  </div>
</section>
<div class="marquee-wrap">
  <div class="marquee-track">
    <div class="marquee-item"><div class="dot"></div>Crypto Monitor</div>
    <div class="marquee-item"><div class="dot"></div>Competitor Intel</div>
    <div class="marquee-item"><div class="dot"></div>Research Analyst</div>
    <div class="marquee-item"><div class="dot"></div>Lead Qualifier</div>
    <div class="marquee-item"><div class="dot"></div>Financial Analyst</div>
    <div class="marquee-item"><div class="dot"></div>Content Writer</div>
    <div class="marquee-item"><div class="dot"></div>Social Monitor</div>
    <div class="marquee-item"><div class="dot"></div>News Tracker</div>
    <div class="marquee-item"><div class="dot"></div>SEO Auditor</div>
    <div class="marquee-item"><div class="dot"></div>Code Reviewer</div>
    <div class="marquee-item"><div class="dot"></div>Legal Researcher</div>
    <div class="marquee-item"><div class="dot"></div>Email Strategist</div>
    <div class="marquee-item"><div class="dot"></div>Crypto Monitor</div>
    <div class="marquee-item"><div class="dot"></div>Competitor Intel</div>
    <div class="marquee-item"><div class="dot"></div>Research Analyst</div>
    <div class="marquee-item"><div class="dot"></div>Lead Qualifier</div>
    <div class="marquee-item"><div class="dot"></div>Financial Analyst</div>
    <div class="marquee-item"><div class="dot"></div>Content Writer</div>
    <div class="marquee-item"><div class="dot"></div>Social Monitor</div>
    <div class="marquee-item"><div class="dot"></div>News Tracker</div>
    <div class="marquee-item"><div class="dot"></div>SEO Auditor</div>
    <div class="marquee-item"><div class="dot"></div>Code Reviewer</div>
    <div class="marquee-item"><div class="dot"></div>Legal Researcher</div>
    <div class="marquee-item"><div class="dot"></div>Email Strategist</div>
  </div>
</div>
<section class="bento" id="features">
  <div class="container">
    <div class="s-label">Platform</div>
    <div class="s-title">A complete AI<br>operations layer</div>
    <div class="bento-grid">
      <div class="bento-card bc-1">
        <div class="bento-big-num">66+</div>
        <div class="bento-title" style="font-size:24px">Specialized AI Agents</div>
        <div class="bento-desc" style="max-width:480px;font-size:14px;color:var(--text2)">Every agent is purpose-built with domain expertise and real tools. Deploy a full AI workforce in minutes, not months.</div>
        <div class="bento-terminal">
          <div class="bt-dim"># Deploy crypto monitor daemon</div>
          <div><span class="bt-green">$</span> apex run crypto-monitor --daemon</div>
          <div class="bt-green">&#10003; Daemon 01b3455e started</div>
          <div class="bt-green">&#10003; Connecting to price feeds...</div>
          <div class="bt-amber">&#9889; ALERT: BTC +8.4% &middot; Sent &#8594; Slack</div>
        </div>
      </div>
      <div class="bento-card bc-2"><span class="bento-icon">&#9889;</span><div class="bento-title">Real-time Daemons</div><div class="bento-desc">Background workers that run continuously and fire alerts the instant thresholds are hit.</div><div class="bento-tag">always-on</div></div>
      <div class="bento-card bc-3"><span class="bento-icon">&#128279;</span><div class="bento-title">Slack + Telegram</div><div class="bento-desc">Results stream directly into your existing workflow. No new apps to check.</div><div class="bento-tag">integrations</div></div>
      <div class="bento-card bc-4"><span class="bento-icon">&#128197;</span><div class="bento-title">Smart Scheduling</div><div class="bento-desc">Cron-based or event-driven triggers. Run agents on your terms.</div><div class="bento-tag">automation</div></div>
      <div class="bento-card bc-5"><span class="bento-icon">&#127970;</span><div class="bento-title">Team Workspaces</div><div class="bento-desc">Org-level accounts, invite-based onboarding, per-member API keys, and audit logs.</div><div class="bento-tag">enterprise</div></div>
      <div class="bento-card bc-6"><span class="bento-icon">&#129504;</span><div class="bento-title">Swarm Memory</div><div class="bento-desc">Agents share a knowledge layer &mdash; research from one feeds context to the next.</div><div class="bento-tag">intelligence</div></div>
      <div class="bento-card bc-7"><span class="bento-icon">&#128202;</span><div class="bento-title">Live Mission Control</div><div class="bento-desc">God-eye dashboard showing every agent, every output, every alert in real time.</div><div class="bento-tag">visibility</div></div>
    </div>
  </div>
</section>
<section class="features-scroll" id="how">
  <div class="container">
    <div class="s-label">How It Works</div>
    <div class="s-title">From idea to<br>autonomous agent</div>
    <div class="features-sticky" style="margin-top:64px">
      <div class="sticky-left">
        <div id="featureList">
          <div class="feature-item active" data-idx="0">
            <div class="feature-num">01 &mdash;</div>
            <div class="feature-title">Pick a specialist</div>
            <div class="feature-desc">Browse 66+ purpose-built agents. Each one tuned for a specific job with real domain knowledge and tools.</div>
          </div>
          <div class="feature-item" data-idx="1">
            <div class="feature-num">02 &mdash;</div>
            <div class="feature-title">Give it a mission</div>
            <div class="feature-desc">Describe the task in plain English. Set conditions, thresholds, and frequency. No code required.</div>
          </div>
          <div class="feature-item" data-idx="2">
            <div class="feature-num">03 &mdash;</div>
            <div class="feature-title">Watch it work</div>
            <div class="feature-desc">Your agent executes in real time. Outputs stream to the dashboard. Alerts fire to Slack or Telegram instantly.</div>
          </div>
          <div class="feature-item" data-idx="3">
            <div class="feature-num">04 &mdash;</div>
            <div class="feature-title">Scale your workforce</div>
            <div class="feature-desc">Run 50 daemons in parallel. Chain agents into pipelines. Build a fully autonomous operation.</div>
          </div>
        </div>
      </div>
      <div id="featureVisuals">
        <div class="feature-visual show" data-idx="0">
          <div class="fv-head"><div class="fv-dot" style="background:#ff5f57"></div><div class="fv-dot" style="background:#febc2e"></div><div class="fv-dot" style="background:#28c840"></div><div class="fv-tag">AGENT CATALOG</div></div>
          <div class="fv-body" style="padding:28px">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px"><div style="font-size:20px;margin-bottom:8px">&#8383;</div><div style="font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif">Crypto Monitor</div><div style="font-size:11px;color:var(--text3);font-family:'DM Sans',sans-serif;margin-top:4px">Price alerts, whale tracking</div></div>
              <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px"><div style="font-size:20px;margin-bottom:8px">&#127919;</div><div style="font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif">Competitor Intel</div><div style="font-size:11px;color:var(--text3);font-family:'DM Sans',sans-serif;margin-top:4px">Track rival moves</div></div>
              <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px"><div style="font-size:20px;margin-bottom:8px">&#128300;</div><div style="font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif">Research Analyst</div><div style="font-size:11px;color:var(--text3);font-family:'DM Sans',sans-serif;margin-top:4px">Deep web research</div></div>
              <div style="background:var(--mintglow);border:1px solid rgba(0,255,170,0.2);border-radius:8px;padding:16px"><div style="font-size:20px;margin-bottom:8px">+63</div><div style="font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;color:var(--mint)">More Agents</div><div style="font-size:11px;color:var(--mint);opacity:.6;font-family:'DM Sans',sans-serif;margin-top:4px">Browse all &#8594;</div></div>
            </div>
          </div>
        </div>
        <div class="feature-visual" data-idx="1">
          <div class="fv-head"><div class="fv-dot" style="background:#ff5f57"></div><div class="fv-dot" style="background:#febc2e"></div><div class="fv-dot" style="background:#28c840"></div><div class="fv-tag">DEPLOY AGENT</div></div>
          <div class="fv-body">
            <div class="bt-dim"># Configure your mission</div>
            <div><span class="bt-green">agent:</span> crypto-monitor</div>
            <div><span class="bt-green">task:</span> Alert when BTC moves 5%+ in any hour</div>
            <div><span class="bt-green">schedule:</span> every 15 minutes</div>
            <div><span class="bt-green">output:</span> slack #trading-alerts</div>
            <br>
            <div style="color:var(--mint)">&#10003; Mission queued &middot; Starting in 3s...</div>
          </div>
        </div>
        <div class="feature-visual" data-idx="2">
          <div class="fv-head"><div class="fv-dot" style="background:#ff5f57"></div><div class="fv-dot" style="background:#febc2e"></div><div class="fv-dot" style="background:#28c840"></div><div class="fv-tag">LIVE FEED</div></div>
          <div class="fv-body">
            <div class="bt-dim">12:04:22 &mdash; crypto-monitor</div>
            <div style="color:var(--amber)">&#9889; BTC: $67,420 &#8594; +8.2% (2h)</div>
            <div style="color:var(--mint)">&rarr; Sent to Slack #trading</div>
            <div class="bt-dim">12:04:31 &mdash; competitor-intel</div>
            <div style="color:var(--text)">&#128204; Competitor updated pricing</div>
            <div style="color:var(--mint)">&rarr; Sent to Telegram</div>
          </div>
        </div>
        <div class="feature-visual" data-idx="3">
          <div class="fv-head"><div class="fv-dot" style="background:#ff5f57"></div><div class="fv-dot" style="background:#febc2e"></div><div class="fv-dot" style="background:#28c840"></div><div class="fv-tag">MISSION CONTROL</div></div>
          <div class="fv-body" style="padding:20px">
            <div style="display:flex;flex-direction:column;gap:8px">
              <div style="display:flex;justify-content:space-between;background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:10px 14px"><span style="font-size:12px;font-family:'DM Sans',sans-serif">crypto-monitor</span><span style="color:var(--mint);font-size:10px">&#9679; RUNNING</span></div>
              <div style="display:flex;justify-content:space-between;background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:10px 14px"><span style="font-size:12px;font-family:'DM Sans',sans-serif">competitor-intel</span><span style="color:var(--mint);font-size:10px">&#9679; RUNNING</span></div>
              <div style="display:flex;justify-content:space-between;background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:10px 14px"><span style="font-size:12px;font-family:'DM Sans',sans-serif">lead-qualifier</span><span style="color:var(--mint);font-size:10px">&#9679; RUNNING</span></div>
              <div style="display:flex;justify-content:space-between;background:var(--mintglow);border:1px solid rgba(0,255,170,0.2);border-radius:6px;padding:10px 14px"><span style="font-size:12px;font-family:'DM Sans',sans-serif;color:var(--mint)">+ 47 more daemons</span><span style="color:var(--mint);font-size:10px">&#9679; ALL ACTIVE</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
<section class="agents" id="agents">
  <div class="container">
    <div class="s-label">The Workforce</div>
    <div class="s-title">Your AI team,<br>ready to hire</div>
  </div>
  <div class="agent-scroll" id="agentScroll">
    <div class="agent-pill"><div class="agent-pill-icon">&#8383;</div><div class="agent-pill-name">Crypto Monitor</div><div class="agent-pill-desc">Price alerts, whale tracking, market conditions 24/7</div><div class="agent-pill-cat">crypto &middot; finance</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#127919;</div><div class="agent-pill-name">Competitor Intel</div><div class="agent-pill-desc">Track pricing, product, and positioning changes</div><div class="agent-pill-cat">strategy &middot; research</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#128300;</div><div class="agent-pill-name">Research Analyst</div><div class="agent-pill-desc">Deep research with web search and source synthesis</div><div class="agent-pill-cat">research &middot; analysis</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#9997;&#65039;</div><div class="agent-pill-name">Copywriter</div><div class="agent-pill-desc">Landing pages, ads, email sequences that convert</div><div class="agent-pill-cat">content &middot; marketing</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#128202;</div><div class="agent-pill-name">Financial Analyst</div><div class="agent-pill-desc">Market analysis, earnings research, investment memos</div><div class="agent-pill-cat">finance &middot; analysis</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#127942;</div><div class="agent-pill-name">Lead Qualifier</div><div class="agent-pill-desc">Research and score leads against your ICP</div><div class="agent-pill-cat">sales &middot; research</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#128240;</div><div class="agent-pill-name">News Monitor</div><div class="agent-pill-desc">Track industry news and surface what matters</div><div class="agent-pill-cat">monitoring &middot; news</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#9878;&#65039;</div><div class="agent-pill-name">Legal Researcher</div><div class="agent-pill-desc">Regulatory changes, compliance alerts</div><div class="agent-pill-cat">legal &middot; compliance</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#128269;</div><div class="agent-pill-name">SEO Auditor</div><div class="agent-pill-desc">Keyword tracking, SERP monitoring, content gaps</div><div class="agent-pill-cat">seo &middot; growth</div></div>
    <div class="agent-pill"><div class="agent-pill-icon">&#128101;</div><div class="agent-pill-name">Social Monitor</div><div class="agent-pill-desc">Brand mentions, sentiment tracking, viral alerts</div><div class="agent-pill-cat">social &middot; monitoring</div></div>
    <div class="agent-pill" style="background:var(--mintglow);border-color:rgba(0,255,170,0.2)"><div class="agent-pill-icon">+</div><div class="agent-pill-name" style="color:var(--mint)">56 More Agents</div><div class="agent-pill-desc" style="color:var(--mint);opacity:.7">Browse the full catalog after signing up</div><div class="agent-pill-cat" style="color:var(--mint)">all categories</div></div>
  </div>
</section>
<section class="pricing" id="pricing">
  <div class="container">
    <div class="s-label">Pricing</div>
    <div class="s-title">Simple, scalable<br>pricing</div>
    <div class="pricing-grid">
      <div class="pc">
        <div class="pc-tier">Starter</div>
        <div class="pc-price"><sup>$</sup>49<sub>/mo</sub></div>
        <div class="pc-desc">For individuals getting started with AI automation.</div>
        <div class="pc-divider"></div>
        <ul class="pc-features"><li>25 agent runs per day</li><li>1 background worker</li><li>3 scheduled tasks</li><li>Telegram alerts</li><li>All 66+ agent types</li><li>API access</li></ul>
        <a href="/signup" class="pc-btn outline">Get Started</a>
      </div>
      <div class="pc featured">
        <div class="pc-badge">POPULAR</div>
        <div class="pc-tier">Pro</div>
        <div class="pc-price"><sup>$</sup>199<sub>/mo</sub></div>
        <div class="pc-desc">For teams that need more power and collaboration.</div>
        <div class="pc-divider"></div>
        <ul class="pc-features"><li>100 agent runs per day</li><li>5 background workers</li><li>10 scheduled tasks</li><li>Slack + Telegram alerts</li><li>5 team seats</li><li>Priority execution</li><li>Workflow automation</li></ul>
        <a href="/signup" class="pc-btn filled">Start Free Trial</a>
      </div>
      <div class="pc">
        <div class="pc-tier">Enterprise</div>
        <div class="pc-price"><sup>$</sup>999<sub>/mo</sub></div>
        <div class="pc-desc">Full AI workforce with enterprise-grade security.</div>
        <div class="pc-divider"></div>
        <ul class="pc-features"><li>Unlimited agent runs</li><li>50 background workers</li><li>Unlimited schedules</li><li>All output channels</li><li>Unlimited team seats</li><li>SSO + Audit logs</li><li>Dedicated SLA support</li></ul>
        <a href="mailto:sales@apexswarm.ai" class="pc-btn outline">Contact Sales</a>
      </div>
    </div>
  </div>
</section>
<section class="final-cta">
  <div class="s-label" style="justify-content:center">Ready to deploy</div>
  <h2>HIRE YOUR<br><span>AI WORKFORCE</span><br>TODAY</h2>
  <p>Start free. Deploy your first agent in 60 seconds. No credit card required.</p>
  <div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap">
    <a href="/signup" class="cta-primary" style="font-size:16px;padding:18px 48px">Deploy Free &rarr;</a>
    <a href="/demo" class="cta-secondary" style="font-size:16px;padding:18px 48px">Live Demo</a>
  </div>
</section>
<footer>
  <div class="footer-logo">APEX SWARM</div>
  <div class="footer-links">
    <a href="#features">Features</a>
    <a href="#pricing">Pricing</a>
    <a href="/demo">Demo</a>
    <a href="/signup">Sign Up</a>
    <a href="/login">Sign In</a>
  </div>
  <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:1px">v4.0.0 &middot; LIVE</div>
</footer>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/ScrollTrigger.min.js"></script>
<script>
gsap.registerPlugin(ScrollTrigger);
const canvas=document.getElementById('particle-canvas');
const ctx=canvas.getContext('2d');
let W,H,particles=[];
function resize(){W=canvas.width=window.innerWidth;H=canvas.height=window.innerHeight}
resize();window.addEventListener('resize',resize);
class Particle{
  constructor(){this.reset(true)}
  reset(init){this.x=Math.random()*W;this.y=init?Math.random()*H:H+10;this.size=Math.random()*1.5+.3;this.speedY=-(Math.random()*.4+.1);this.speedX=(Math.random()-.5)*.15;this.opacity=Math.random()*.5+.1;this.life=0;this.maxLife=Math.random()*300+200}
  update(){this.x+=this.speedX;this.y+=this.speedY;this.life++;if(this.life>this.maxLife)this.reset(false)}
  draw(){const fade=Math.min(this.life/40,1)*Math.min((this.maxLife-this.life)/40,1);ctx.globalAlpha=this.opacity*fade;ctx.fillStyle='#00ffaa';ctx.beginPath();ctx.arc(this.x,this.y,this.size,0,Math.PI*2);ctx.fill()}
}
for(let i=0;i<120;i++)particles.push(new Particle());
function animCanvas(){ctx.clearRect(0,0,W,H);particles.forEach(p=>{p.update();p.draw()});requestAnimationFrame(animCanvas)}
animCanvas();
const cur=document.getElementById('cursor');
const fol=document.getElementById('cursor-follower');
let mx=0,my=0,fx=0,fy=0;
document.addEventListener('mousemove',e=>{mx=e.clientX;my=e.clientY;cur.style.left=mx+'px';cur.style.top=my+'px'});
(function animCursor(){fx+=(mx-fx)*.12;fy+=(my-fy)*.12;fol.style.left=fx+'px';fol.style.top=fy+'px';requestAnimationFrame(animCursor)})();
document.querySelectorAll('a,button,.bento-card,.agent-pill').forEach(el=>{
  el.addEventListener('mouseenter',()=>{cur.style.width='16px';cur.style.height='16px';fol.style.width='48px';fol.style.height='48px';fol.style.borderColor='rgba(0,255,170,0.6)'});
  el.addEventListener('mouseleave',()=>{cur.style.width='8px';cur.style.height='8px';fol.style.width='32px';fol.style.height='32px';fol.style.borderColor='rgba(0,255,170,0.4)'});
});
window.addEventListener('scroll',()=>document.getElementById('nav').classList.toggle('scrolled',window.scrollY>60));
const tl=gsap.timeline({delay:.1});
tl.to('.hero-eyebrow',{opacity:1,y:0,duration:.7,ease:'power3.out'})
  .to('.hero-title .word',{y:0,opacity:1,duration:.9,ease:'power4.out',stagger:.08},'-=.3')
  .to('.hero-sub',{opacity:1,y:0,duration:.7,ease:'power3.out'},'-=.4')
  .to('.hero-cta',{opacity:1,y:0,duration:.6,ease:'power3.out'},'-=.4')
  .to('.hero-metrics',{opacity:1,y:0,duration:.6,ease:'power3.out'},'-=.3');
gsap.from('.bento-card',{opacity:0,y:40,duration:.8,stagger:.06,ease:'power3.out',scrollTrigger:{trigger:'.bento-grid',start:'top 80%'}});
document.querySelectorAll('.bento-card').forEach(card=>{
  card.addEventListener('mousemove',e=>{const r=card.getBoundingClientRect();card.style.setProperty('--mx',((e.clientX-r.left)/r.width*100)+'%');card.style.setProperty('--my',((e.clientY-r.top)/r.height*100)+'%')});
});
const featureItems=document.querySelectorAll('.feature-item');
const featureVisuals=document.querySelectorAll('.feature-visual');
featureItems.forEach(item=>{
  item.addEventListener('click',()=>{
    const idx=item.dataset.idx;
    featureItems.forEach(f=>f.classList.remove('active'));
    featureVisuals.forEach(v=>{v.classList.remove('show');v.style.display='none'});
    item.classList.add('active');
    const vis=document.querySelector('.feature-visual[data-idx="'+idx+'"]');
    vis.style.display='block';requestAnimationFrame(()=>vis.classList.add('show'));
  });
});
let fi=0;
setInterval(()=>{
  fi=(fi+1)%4;
  featureItems.forEach(f=>f.classList.remove('active'));
  featureVisuals.forEach(v=>{v.classList.remove('show');v.style.display='none'});
  featureItems[fi].classList.add('active');
  const vis=document.querySelector('.feature-visual[data-idx="'+fi+'"]');
  vis.style.display='block';requestAnimationFrame(()=>vis.classList.add('show'));
},3000);
gsap.from('.agent-pill',{opacity:0,x:40,duration:.7,stagger:.05,ease:'power3.out',scrollTrigger:{trigger:'#agentScroll',start:'top 85%'}});
gsap.from('.pc',{opacity:0,y:48,duration:.8,stagger:.1,ease:'power3.out',scrollTrigger:{trigger:'.pricing-grid',start:'top 80%'}});
gsap.utils.toArray('.s-label,.s-title').forEach(el=>{gsap.from(el,{opacity:0,y:32,duration:.7,ease:'power3.out',scrollTrigger:{trigger:el,start:'top 88%'}})});
gsap.from('.final-cta h2',{opacity:0,y:60,duration:1,ease:'power4.out',scrollTrigger:{trigger:'.final-cta',start:'top 75%'}});
gsap.from('.final-cta p,.final-cta .cta-primary,.final-cta .cta-secondary',{opacity:0,y:32,duration:.7,stagger:.1,ease:'power3.out',scrollTrigger:{trigger:'.final-cta',start:'top 70%'}});
</script>
</body>
</html>"""

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX SWARM — Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e2e8f0;font-family:system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#13131a;border:1px solid #1e1e2e;border-radius:16px;padding:40px;width:100%;max-width:420px}
.logo{font-size:28px;font-weight:700;color:#a78bfa;margin-bottom:8px}
.subtitle{font-size:13px;color:#64748b;margin-bottom:32px}
label{font-size:12px;color:#94a3b8;font-weight:500;display:block;margin-bottom:8px;text-transform:uppercase}
input{width:100%;background:#0a0a0f;border:1px solid #1e1e2e;border-radius:8px;padding:12px 16px;color:#e2e8f0;font-size:13px;outline:none}
button{width:100%;margin-top:16px;padding:13px;background:#a78bfa;color:#0a0a0f;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
.error{margin-top:12px;padding:10px 14px;background:#2d1b1b;border:1px solid #7f1d1d;border-radius:8px;font-size:12px;color:#fca5a5;display:none}
.buy-link{display:block;text-align:center;margin-top:20px;font-size:12px;color:#64748b}
.buy-link a{color:#a78bfa;text-decoration:none}
</style>
</head>
<body>
<div class="card">
<div class="logo">⚡ APEX SWARM</div>
<div class="subtitle">Enter your license key to access the platform</div>
<label>License Key</label>
<input type="text" id="licenseKey" placeholder="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX">
<button onclick="doLogin()">Activate Access</button>
<div class="error" id="errMsg"></div>
<div class="buy-link">No key? <a href="https://colepresley.gumroad.com/l/apex-swarm" target="_blank">Get APEX SWARM →</a></div>
</div>
<script>
if(localStorage.getItem("apex_key")){window.location.href="/dashboard"}
document.getElementById("licenseKey").addEventListener("keydown",e=>{if(e.key==="Enter")doLogin()});
async function doLogin(){
  const key=document.getElementById("licenseKey").value.trim();
  if(!key){showError("Please enter your license key.");return;}
  try{
    const res=await fetch("/api/v1/license/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({license_key:key})});
    const data=await res.json();
    if(data.valid){localStorage.setItem("apex_key",key);localStorage.setItem("apex_tier",data.tier);window.location.href="/dashboard";}
    else{showError(data.error||"Invalid license key.");}
  }catch(e){showError("Connection error. Please try again.");}
}
function showError(msg){const e=document.getElementById("errMsg");e.textContent=msg;e.style.display="block";}
</script>
</body>
</html>
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX SWARM — Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Sans:wght@400;500;600;700&family=Playfair+Display:wght@700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}

:root{
  --bg:#06060a;--bg2:#0a0a12;--surface:#0e0e18;--surface2:#141422;--surface3:#1a1a2e;
  --border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.1);
  --text:#f0f0f8;--text2:#8888a8;--text3:#555570;
  --mint:#00f0a0;--mint2:#00cc80;--mintbg:rgba(0,240,160,0.06);--mintglow:rgba(0,240,160,0.15);
  --cyan:#00d4ff;--cyanbg:rgba(0,212,255,0.06);
  --amber:#ffb800;--amberbg:rgba(255,184,0,0.06);
  --rose:#ff3366;--rosebg:rgba(255,51,102,0.06);
  --violet:#7733ff;--violetbg:rgba(119,51,255,0.06);
}

html{font-size:15px}
body{background:var(--bg);color:var(--text);font-family:'Instrument Sans',sans-serif;overflow-x:hidden;min-height:100vh}
::selection{background:var(--mint);color:var(--bg)}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

/* ─── GRAIN OVERLAY ─── */
body::before{content:'';position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
}

/* ─── LAYOUT ─── */
.app{display:grid;grid-template-columns:260px 1fr;grid-template-rows:1fr;height:100vh}
.sidebar{background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow-y:auto}
.main{overflow-y:auto;position:relative}

/* ─── SIDEBAR ─── */
.sidebar-header{padding:28px 24px 20px;border-bottom:1px solid var(--border)}
.logo-mark{font-family:'Playfair Display',serif;font-weight:900;font-size:22px;letter-spacing:-0.5px;background:linear-gradient(135deg,var(--mint),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.logo-sub{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text3);letter-spacing:3px;text-transform:uppercase;margin-top:6px}

.nav-group{padding:20px 12px}
.nav-group-label{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--text3);padding:0 12px;margin-bottom:10px}
.nav-btn{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;cursor:pointer;font-size:13.5px;color:var(--text2);transition:all 0.2s;border:1px solid transparent;margin-bottom:2px}
.nav-btn:hover{color:var(--text);background:rgba(255,255,255,0.03)}
.nav-btn.active{color:var(--mint);background:var(--mintbg);border-color:rgba(0,240,160,0.1)}
.nav-btn .icon{font-size:17px;width:24px;text-align:center;opacity:0.8}
.nav-btn.active .icon{opacity:1}
.nav-badge{margin-left:auto;font-family:'IBM Plex Mono',monospace;font-size:9px;background:var(--mint);color:var(--bg);padding:2px 7px;border-radius:8px;font-weight:600}

.sidebar-footer{margin-top:auto;padding:16px 24px;border-top:1px solid var(--border);display:flex;flex-direction:column;align-items:stretch;gap:8px}
.pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--mint);box-shadow:0 0 12px var(--mintglow);animation:breathe 3s ease infinite}
@keyframes breathe{0%,100%{opacity:1;box-shadow:0 0 12px var(--mintglow)}50%{opacity:0.5;box-shadow:0 0 4px var(--mintglow)}}
.sidebar-status{font-size:11px;color:var(--text2)}
.sidebar-status span{color:var(--mint);font-weight:600}

/* ─── MAIN CONTENT ─── */
.page{padding:32px 36px;max-width:1400px}
.page-header{margin-bottom:28px}
.page-title{font-family:'Playfair Display',serif;font-size:32px;font-weight:800;letter-spacing:-0.5px}
.page-subtitle{color:var(--text2);font-size:14px;margin-top:6px}

/* ─── METRIC CARDS ─── */
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px}
.metric{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px 22px;position:relative;overflow:hidden;transition:border-color 0.3s}
.metric:hover{border-color:var(--border2)}
.metric::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--mint),transparent);opacity:0;transition:opacity 0.3s}
.metric:hover::after{opacity:1}
.metric-val{font-family:'IBM Plex Mono',monospace;font-size:32px;font-weight:600;line-height:1}
.metric-label{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:2px;margin-top:8px}
.metric-change{font-size:11px;margin-top:6px;font-family:'IBM Plex Mono',monospace}
.metric-change.up{color:var(--mint)}
.metric-change.down{color:var(--rose)}

/* ─── CARDS ─── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;overflow:hidden}
.card-head{padding:18px 22px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.card-title{font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px}
.card-body{padding:18px 22px}

/* ─── GRIDS ─── */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.g23{display:grid;grid-template-columns:2fr 1fr;gap:14px}
.g32{display:grid;grid-template-columns:1fr 2fr;gap:14px}

/* ─── BUTTONS ─── */
.btn{padding:9px 18px;border-radius:9px;border:1px solid var(--border);background:transparent;color:var(--text);font-family:'Instrument Sans',sans-serif;font-size:13px;font-weight:500;cursor:pointer;transition:all 0.2s;display:inline-flex;align-items:center;gap:7px}
.btn:hover{border-color:var(--border2);background:rgba(255,255,255,0.03)}
.btn-mint{background:var(--mint);color:var(--bg);border-color:var(--mint);font-weight:600}
.btn-mint:hover{background:var(--mint2);transform:translateY(-1px);box-shadow:0 4px 20px var(--mintglow)}
.btn-sm{padding:6px 12px;font-size:12px;border-radius:7px}

/* ─── FORMS ─── */
.input,.select,.textarea{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:9px;font-family:'Instrument Sans',sans-serif;font-size:13.5px;width:100%;outline:none;transition:border-color 0.2s}
.input:focus,.select:focus,.textarea:focus{border-color:var(--mint)}
.textarea{min-height:100px;resize:vertical}
.form-label{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;display:block}

/* ─── AGENT ROW ─── */
.agent-row{display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid var(--border)}
.agent-row:last-child{border-bottom:none}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot.live{background:var(--mint);box-shadow:0 0 8px var(--mintglow);animation:breathe 2s ease infinite}
.dot.done{background:var(--cyan)}
.dot.err{background:var(--rose)}
.dot.idle{background:var(--text3)}
.agent-info{flex:1;min-width:0}
.agent-name{font-weight:500;font-size:13.5px}
.agent-task{color:var(--text2);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.agent-time{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--text3)}
.agent-badge{font-size:10px;padding:3px 8px;border-radius:6px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
.badge-live{background:var(--mintbg);color:var(--mint)}
.badge-done{background:var(--cyanbg);color:var(--cyan)}
.badge-err{background:var(--rosebg);color:var(--rose)}

/* ─── EVENT FEED ─── */
.event-item{padding:10px 0;border-bottom:1px solid var(--border);display:flex;gap:12px;align-items:flex-start}
.event-item:last-child{border-bottom:none}
.event-dot{width:6px;height:6px;border-radius:50%;margin-top:6px;flex-shrink:0}
.event-content{flex:1;font-size:13px}
.event-time{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text3)}

/* ─── ORG CHART ─── */
.org-node{background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:16px;text-align:center;transition:all 0.2s}
.org-node:hover{border-color:var(--mint);transform:translateY(-2px)}
.org-icon{font-size:28px;margin-bottom:6px}
.org-role{font-weight:600;font-size:13px}
.org-tools{font-size:11px;color:var(--text3);margin-top:4px}

/* ─── MARKETPLACE ─── */
.mp-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px;cursor:pointer;transition:all 0.25s;position:relative}
.mp-card:hover{border-color:var(--mint);transform:translateY(-3px);box-shadow:0 12px 40px rgba(0,0,0,0.3)}
.mp-card-icon{font-size:36px;margin-bottom:10px}
.mp-card-name{font-weight:600;font-size:15px;margin-bottom:4px}
.mp-card-desc{color:var(--text2);font-size:12.5px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:12px}
.mp-card-footer{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--text3)}
.mp-price{font-family:'IBM Plex Mono',monospace;color:var(--mint);font-weight:600}

/* ─── GOAL PROGRESS ─── */
.goal-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px;margin-bottom:14px}
.goal-progress{height:4px;background:var(--surface3);border-radius:2px;margin-top:12px;overflow:hidden}
.goal-fill{height:100%;background:linear-gradient(90deg,var(--mint),var(--cyan));border-radius:2px;transition:width 0.5s ease}

/* ─── SYSTEM STATUS GRID ─── */
.status-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.status-item{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--surface2);border-radius:8px;font-size:12px}
.status-on{color:var(--mint)}
.status-off{color:var(--text3)}

/* ─── MODAL ─── */
.modal-bg{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;z-index:1000;backdrop-filter:blur(8px)}
.modal-box{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:32px;max-width:640px;width:90%;max-height:80vh;overflow-y:auto}

/* ─── ANIMATIONS ─── */
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.fade-up{animation:fadeUp 0.4s ease}
@keyframes slideRight{from{opacity:0;transform:translateX(-16px)}to{opacity:1;transform:translateX(0)}}
.slide-r{animation:slideRight 0.35s ease}

/* ─── LOADING ─── */
.spin{width:18px;height:18px;border:2px solid var(--border);border-top-color:var(--mint);border-radius:50%;animation:sp 0.5s linear infinite;display:inline-block}
@keyframes sp{to{transform:rotate(360deg)}}

/* ─── RESPONSIVE ─── */
@media(max-width:900px){.app{grid-template-columns:1fr}.sidebar{display:none}.metrics{grid-template-columns:1fr 1fr}.g2,.g3,.g23,.g32{grid-template-columns:1fr}}
</style>
</head>
<body>

<div class="app" id="app">
  <!-- SIDEBAR -->
  <div class="sidebar">
    <div class="sidebar-header">
      <div class="logo-mark">APEX SWARM</div>
      <div class="logo-sub">Command Center</div>
    </div>

    <div class="nav-group">
      <div class="nav-group-label">Operations</div>
      <div class="nav-btn active" data-p="overview" onclick="go('overview')"><span class="icon">◉</span> Overview</div>
      <div class="nav-btn" data-p="deploy" onclick="go('deploy')"><span class="icon">⚡</span> Deploy</div>
      <div class="nav-btn" data-p="agents" onclick="go('agents')"><span class="icon">◈</span> Agents</div>
      <div class="nav-btn" data-p="feed" onclick="go('feed')"><span class="icon">◎</span> Live Feed</div>
    </div>
    <div class="nav-group">
      <div class="nav-group-label">Intelligence</div>
      <div class="nav-btn" data-p="goals" onclick="go('goals')"><span class="icon">◆</span> Goals<span class="nav-badge">NEW</span></div>
      <div class="nav-btn" data-p="a2a" onclick="go('a2a')"><span class="icon">◇</span> Swarm Delegate</div>
      <div class="nav-btn" data-p="swarm" onclick="go('swarm')"><span class="icon">⬡</span> Live Swarm</div>
      <div class="nav-btn" data-p="daemons" onclick="go('daemons')"><span class="icon">◌</span> Daemons</div>
      <div class="nav-btn" data-p="workflows" onclick="go('workflows')"><span class="icon">⬡</span> Workflows</div>
    </div>
    <div class="nav-group">
      <div class="nav-group-label">Platform</div>
      <div class="nav-btn" data-p="marketplace" onclick="go('marketplace')"><span class="icon">◫</span> Marketplace</div>
      <div class="nav-btn" data-p="models" onclick="go('models')"><span class="icon">◑</span> Models</div>
      <div class="nav-btn" data-p="team" onclick="go('team')"><span class="icon">◰</span> Team</div>
      <div class="nav-btn" data-p="org" onclick="go('org')"><span class="icon">◑</span> Org Chart</div>
      <div class="nav-btn" data-p="settings" onclick="go('settings')"><span class="icon">◎</span> System</div>
    </div>

    <div class="nav-btn" data-p="admin" onclick="go('admin')"><span class="icon">&#9881;</span> Admin</div>
      <div class="sidebar-footer" style="flex-direction:column;align-items:stretch;gap:8px">
      <button onclick="signOut()" style="background:none;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:8px 14px;color:var(--text3);font-size:12px;cursor:pointer;text-align:left;transition:all 0.2s" onmouseover="this.style.color='var(--rose)';this.style.borderColor='var(--rose)'" onmouseout="this.style.color='var(--text3)';this.style.borderColor='rgba(255,255,255,0.08)'">&#8594; Sign Out</button>
      <div class="pulse-dot"></div>
      <div class="sidebar-status"><span>Live</span> · v__VERSION__</div>
    </div>
  </div>

  <!-- MAIN -->
  <div class="main" id="main"></div>
</div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
let KEY = localStorage.getItem('apex_key') || '';
let BASE = location.origin;
if(!KEY){KEY='dev-mode';localStorage.setItem('apex_key','dev-mode');}
let page = 'overview';
let events = [];
let sse = null;

async function loadInitialEvents() {
  try {
    const r = await fetch(BASE + '/api/v1/events?limit=50', { headers: { 'X-Api-Key': KEY } });
    const d = await r.json();
    if (d.events && d.events.length) {
      events = d.events;
      if (page === 'feed') pFeed();
      if (page === 'overview') {
        const f = document.querySelector('#overviewFeed');
        if (f) f.innerHTML = events.slice(-6).reverse().map(ev => '<div class="event-item"><div class="event-dot" style="background:var(--mint)"></div><div class="event-content">' + (ev.agent_name||ev.agent_type||'—') + '<div class="event-time">' + new Date(ev.timestamp).toLocaleTimeString() + '</div></div></div>').join('');
      }
    }
  } catch(e) { console.error('Failed to load events:', e); }
}

async function api(p, o = {}) {
  try {
    const r = await fetch(BASE + p, { ...o, headers: { 'X-Api-Key': KEY, 'Content-Type': 'application/json', ...o.headers } });
    return await r.json();
  } catch(e) { return { error: e.message }; }
}

function go(p) {
  page = p;
  $$('.nav-btn').forEach(n => n.classList.toggle('active', n.dataset.p === p));
  $('#main').innerHTML = '<div style="display:flex;justify-content:center;padding:60px"><div class="spin"></div></div>';
  const R = {overview:pOverview,deploy:pDeploy,agents:pAgents,feed:pFeed,goals:pGoals,a2a:pA2A,swarm:pSwarm,daemons:pDaemons,admin:pAdmin,admin:pAdmin,workflows:pWorkflows,marketplace:pMarketplace,models:pModels,team:pTeam,org:pOrg,settings:pSettings};
  (R[p]||pOverview)();
}

// ─── OVERVIEW ──────────────────────────
async function pOverview() {
  const [h, ge, mp] = await Promise.all([api('/api/v1/health'), api('/api/v1/god-eye'), api('/api/v1/marketplace/stats')]);
  const sys = h || {};
  const g = ge || {};
  const m = mp || {};
  $('#main').innerHTML = `<div class="page fade-up">
    <div class="page-header"><div class="page-title">Command Center</div><div class="page-subtitle">Real-time swarm intelligence overview</div></div>
    <div class="metrics">
      <div class="metric"><div class="metric-val" style="color:var(--mint)">${g.active_agents||0}</div><div class="metric-label">Active Agents</div></div>
      <div class="metric"><div class="metric-val" style="color:var(--cyan)">${g.active_daemons||0}</div><div class="metric-label">Daemons</div></div>
      <div class="metric"><div class="metric-val" style="color:var(--amber)">${g.total_events||0}</div><div class="metric-label">Events</div></div>
      <div class="metric"><div class="metric-val" style="color:var(--violet)">${m.published_agents||0}</div><div class="metric-label">Marketplace</div></div>
    </div>
    <div class="g23" style="margin-bottom:14px">
      <div class="card"><div class="card-head"><div class="card-title">◉ System Status</div><div style="font-size:11px;color:var(--mint)">v${sys.version||'4.0'}</div></div>
        <div class="card-body"><div class="status-grid">
          ${Object.entries({Tools:sys.tools,Chains:sys.chains,Knowledge:sys.knowledge,'Mission Ctrl':sys.mission_control,Memory:sys.swarm_memory,MCP:sys.mcp_registry,'Multi-Model':sys.multi_model,Marketplace:sys.marketplace,Voice:sys.voice,Workflows:sys.workflows,A2A:sys.a2a_protocol,Goals:sys.autonomous_goals,Enterprise:sys.enterprise}).map(([k,v])=>`<div class="status-item"><div class="dot ${v?'live':'idle'}"></div><span class="${v?'status-on':'status-off'}">${k}</span></div>`).join('')}
        </div></div>
      </div>
      <div class="card"><div class="card-head"><div class="card-title">◎ Live Events</div></div>
        <div class="card-body" id="overviewFeed" style="max-height:280px;overflow-y:auto">${events.length?events.slice(-6).reverse().map(e=>`<div class="event-item"><div class="event-dot" style="background:var(--mint)"></div><div class="event-content">${e.agent_name||e.agent_type||'—'}<div class="event-time">${new Date(e.timestamp).toLocaleTimeString()}</div></div></div>`).join(''):'<div style="color:var(--text3);font-size:13px;padding:20px 0;text-align:center">Waiting for events...</div>'}</div>
      </div>
    </div>
    <div class="g3">
      <div class="card" style="cursor:pointer" onclick="go('deploy')"><div class="card-body" style="text-align:center;padding:28px"><div style="font-size:28px;margin-bottom:8px">⚡</div><div style="font-weight:600">Deploy Agent</div><div style="color:var(--text3);font-size:12px;margin-top:4px">66+ specialized agents</div></div></div>
      <div class="card" style="cursor:pointer" onclick="go('goals')"><div class="card-body" style="text-align:center;padding:28px"><div style="font-size:28px;margin-bottom:8px">◆</div><div style="font-weight:600">Launch Goal</div><div style="color:var(--text3);font-size:12px;margin-top:4px">Autonomous execution</div></div></div>
      <div class="card" style="cursor:pointer" onclick="go('marketplace')"><div class="card-body" style="text-align:center;padding:28px"><div style="font-size:28px;margin-bottom:8px">◫</div><div style="font-weight:600">Marketplace</div><div style="color:var(--text3);font-size:12px;margin-top:4px">Browse & install agents</div></div></div>
    </div>
  </div>`;
}

// ─── DEPLOY ──────────────────────────
async function pDeploy() {
  const [ag, mo] = await Promise.all([api('/api/v1/agents'), api('/api/v1/models/available')]);
  const agents = (ag.agents||[]).map(a=>`<option value="${a.type}">${a.name}</option>`).join('');
  const models = (mo.models||[]).map(m=>`<option value="${m.model_id}">${m.provider_name||m.provider}: ${m.name}</option>`).join('');
  $('#main').innerHTML = `<div class="page fade-up">
    <div class="page-header"><div class="page-title">Deploy Agent</div><div class="page-subtitle">Select an agent, give it a task, choose a model</div></div>
    <div class="g2">
      <div class="card"><div class="card-body" style="display:flex;flex-direction:column;gap:14px">
        <div><div class="form-label">Agent</div><select class="select" id="dAgent">${agents}</select></div>
        <div><div class="form-label">Model</div><select class="select" id="dModel"><option value="">Default (Claude Haiku)</option>${models}</select></div>
        <div><div class="form-label">Task</div><textarea class="textarea" id="dTask" placeholder="Describe the task..."></textarea></div>
        <button class="btn btn-mint" onclick="doDeploy()" id="dBtn">⚡ Deploy Agent</button>
        <div id="dResult"></div>
      </div></div>
      <div class="card"><div class="card-head"><div class="card-title">Recent</div></div><div class="card-body" id="dRecent"></div></div>
    </div></div>`;
  loadRecent();
}
async function doDeploy() {
  const b=$('#dBtn'); b.innerHTML='<div class="spin"></div>'; b.disabled=true;
  const d={agent_type:$('#dAgent').value,task_description:$('#dTask').value}; const m=$('#dModel').value; if(m)d.model=m;
  const r=await api('/api/v1/deploy',{method:'POST',body:JSON.stringify(d)});
  b.innerHTML='⚡ Deploy Agent'; b.disabled=false;
  $('#dResult').innerHTML=r.agent_id?`<div style="background:var(--mintbg);border:1px solid rgba(0,240,160,0.2);border-radius:10px;padding:14px;font-size:13px">✓ <strong>${r.agent_name||r.agent_type}</strong> deployed · <code style="font-size:11px;color:var(--text2)">${r.agent_id.slice(0,12)}</code></div>`:`<div style="color:var(--rose)">${r.detail||r.error||'Failed'}</div>`;
  loadRecent();
}
async function loadRecent() {
  const r=await api('/api/v1/agents/recent?limit=8');
  const el=$('#dRecent'); if(!el)return;
  el.innerHTML=(r.agents||[]).map(a=>`<div class="agent-row"><div class="dot ${a.status==='running'?'live':a.status==='completed'?'done':'err'}"></div><div class="agent-info"><div class="agent-name">${a.agent_type}</div><div class="agent-task">${(a.task_description||'').slice(0,60)}</div></div><span class="agent-badge ${a.status==='completed'?'badge-done':a.status==='running'?'badge-live':'badge-err'}">${a.status}</span></div>`).join('')||'<div style="color:var(--text3);text-align:center;padding:20px">No agents yet</div>';
}

// ─── AGENTS ──────────────────────────
async function pAgents() {
  const r=await api('/api/v1/agents/recent?limit=30');
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Agent History</div></div>
    <div class="card"><div class="card-body">${(r.agents||[]).map(a=>`<div class="agent-row" style="cursor:pointer" onclick="viewAgent('${a.id}')"><div class="dot ${a.status==='running'?'live':a.status==='completed'?'done':'err'}"></div><div class="agent-info"><div class="agent-name">${a.agent_type}</div><div class="agent-task">${(a.task_description||'').slice(0,100)}</div></div><span class="agent-badge ${a.status==='completed'?'badge-done':a.status==='running'?'badge-live':'badge-err'}">${a.status}</span></div>`).join('')||'<div style="text-align:center;padding:40px;color:var(--text3)">No agents deployed yet</div>'}</div></div></div>`;
}
async function viewAgent(id) {
  const r=await api('/api/v1/status/'+id); if(!r||!r.result)return;
  const o=document.createElement('div');o.className='modal-bg';o.onclick=e=>{if(e.target===o)o.remove()};
  o.innerHTML=`<div class="modal-box"><div style="font-weight:700;font-size:18px;margin-bottom:12px">${r.agent_type}</div><div style="color:var(--text2);font-size:12px;margin-bottom:16px">${r.status}</div><div style="white-space:pre-wrap;font-size:13.5px;line-height:1.7;max-height:50vh;overflow-y:auto">${(r.result||'').replace(/</g,'&lt;')}</div><button class="btn" style="margin-top:16px" onclick="this.closest('.modal-bg').remove()">Close</button></div>`;
  document.body.appendChild(o);
}

// ─── LIVE FEED ──────────────────────────
function pFeed() {
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Live Feed</div><div class="page-subtitle">Real-time event stream from all agents</div></div>
    <div class="card"><div class="card-body" id="feedBox" style="min-height:400px;max-height:65vh;overflow-y:auto">${events.length?events.slice().reverse().map(e=>`<div class="event-item"><div class="event-dot" style="background:${e.event_type?.includes('fail')?'var(--rose)':e.event_type?.includes('alert')?'var(--amber)':'var(--mint)'}"></div><div class="event-content"><strong>${e.agent_name||e.agent_type||'system'}</strong> · ${(e.message||'').slice(0,150)}<div class="event-time">${new Date(e.timestamp).toLocaleTimeString()}</div></div></div>`).join(''):'<div style="text-align:center;padding:40px;color:var(--text3)"><div class="spin" style="margin-bottom:12px"></div><br>Listening for events...</div>'}</div></div></div>`;
}

// ─── GOALS ──────────────────────────
async function pGoals() {
  const [goals,roles]=await Promise.all([api('/api/v1/goals'),api('/api/v1/roles')]);
  const rl=roles.roles||[];
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Autonomous Goals</div><div class="page-subtitle">Define a business objective — the swarm builds a team and executes</div></div>
    <div class="g23">
      <div class="card"><div class="card-body" style="display:flex;flex-direction:column;gap:14px">
        <div><div class="form-label">Goal</div><input class="input" id="gTitle" placeholder="e.g. Launch a weekly DeFi newsletter"></div>
        <div><div class="form-label">Description</div><textarea class="textarea" id="gDesc" placeholder="Detailed objective..."></textarea></div>
        <div><div class="form-label">Team</div><div style="display:flex;flex-wrap:wrap;gap:6px" id="gRoles">${rl.map(r=>`<label style="display:flex;align-items:center;gap:4px;font-size:12px;padding:5px 10px;background:var(--surface2);border-radius:7px;cursor:pointer"><input type="checkbox" value="${r.role_id}" ${['ceo','researcher','writer','analyst'].includes(r.role_id)?'checked':''}>${r.icon} ${r.name}</label>`).join('')}</div></div>
        <button class="btn btn-mint" onclick="launchGoal()" id="gBtn">◆ Launch Goal</button>
        <div id="gResult"></div>
      </div></div>
      <div class="card"><div class="card-head"><div class="card-title">How It Works</div></div><div class="card-body" style="color:var(--text2);font-size:13px;line-height:2">
        <div>1 → <strong style="color:var(--text)">You define</strong> the goal</div>
        <div>2 → <strong style="color:var(--text)">AI decomposes</strong> into projects & tasks</div>
        <div>3 → <strong style="color:var(--text)">Roles assigned</strong> (CEO, Analyst, Writer...)</div>
        <div>4 → <strong style="color:var(--text)">Agents execute</strong> in parallel</div>
        <div>5 → <strong style="color:var(--text)">Results synthesized</strong> into one report</div>
      </div></div>
    </div>
    ${(goals.goals||[]).length?`<div style="margin-top:20px">${(goals.goals||[]).reverse().map(g=>`<div class="goal-card"><div style="display:flex;justify-content:space-between;align-items:center"><div><strong>${g.title}</strong><div style="color:var(--text2);font-size:12px;margin-top:4px">${g.projects_count} projects · ${g.tasks_total} tasks</div></div><div style="font-family:'IBM Plex Mono',monospace;font-size:24px;font-weight:600;color:var(--mint)">${g.progress}%</div></div><div class="goal-progress"><div class="goal-fill" style="width:${g.progress}%"></div></div></div>`).join('')}</div>`:''}</div>`;
}
async function launchGoal() {
  const b=$('#gBtn');b.innerHTML='<div class="spin"></div>';b.disabled=true;
  const roles=[...$('#gRoles').querySelectorAll('input:checked')].map(i=>i.value);
  const r=await api('/api/v1/goals',{method:'POST',body:JSON.stringify({title:$('#gTitle').value,description:$('#gDesc').value,org_roles:roles})});
  b.innerHTML='◆ Launch Goal';b.disabled=false;
  $('#gResult').innerHTML=r.goal_id?`<div style="background:var(--mintbg);border:1px solid rgba(0,240,160,0.2);border-radius:10px;padding:14px">✓ Goal complete — ${r.tasks_completed}/${r.tasks_total} tasks · <strong>${r.progress}%</strong></div>`:`<div style="color:var(--rose)">${r.detail||r.error||'Failed'}</div>`;
}

// ─── A2A ──────────────────────────
async function pA2A() {
  const s=await api('/api/v1/a2a/stats');
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Swarm Delegate</div><div class="page-subtitle">Give a complex task — agents decompose, delegate, and synthesize</div></div>
    <div class="g23">
      <div class="card"><div class="card-body" style="display:flex;flex-direction:column;gap:14px">
        <div><div class="form-label">Complex Task</div><textarea class="textarea" id="a2aTask" placeholder="e.g. Research top 5 AI startups, analyze business models, write investment report"></textarea></div>
        <button class="btn btn-mint" onclick="doA2A()" id="a2aBtn">◇ Delegate to Swarm</button>
        <div id="a2aResult"></div>
      </div></div>
      <div class="card"><div class="card-body"><div class="metric-val" style="color:var(--cyan)">${(s||{}).total_plans||0}</div><div class="metric-label">Total Plans</div><div style="margin-top:16px"><div class="metric-val" style="color:var(--amber)">${(s||{}).total_subtasks||0}</div><div class="metric-label">Total Subtasks</div></div></div></div>
    </div></div>`;
}
async function doA2A() {
  const b=$('#a2aBtn');b.innerHTML='<div class="spin"></div>';b.disabled=true;
  const r=await api('/api/v1/a2a/delegate',{method:'POST',body:JSON.stringify({task:$('#a2aTask').value})});
  b.innerHTML='◇ Delegate to Swarm';b.disabled=false;
  if(r.plan_id){const sub=(r.subtasks||[]).map(s=>`<div class="agent-row"><div class="dot ${s.status==='completed'?'done':'err'}"></div><div class="agent-info"><div class="agent-name">${s.agent_type}</div><div class="agent-task">${(s.description||'').slice(0,80)}</div></div><span class="agent-badge ${s.status==='completed'?'badge-done':'badge-err'}">${s.status}</span></div>`).join('');
  $('#a2aResult').innerHTML=`<div class="card" style="margin-top:12px"><div class="card-body">${sub}${r.final_result?`<div style="margin-top:14px;padding:14px;background:var(--bg);border-radius:10px;font-size:13px;white-space:pre-wrap;max-height:300px;overflow-y:auto">${r.final_result.replace(/</g,'&lt;')}</div>`:''}</div></div>`;}
  else{$('#a2aResult').innerHTML=`<div style="color:var(--rose)">${r.detail||r.error||'Failed'}</div>`;}
}

// ─── DAEMONS ──────────────────────────
async function pSwarm() {
  const [daemonRes, evtRes] = await Promise.all([api('/api/v1/daemons'), api('/api/v1/events?limit=50')]);
  const daemons = daemonRes.daemons || [];
  const evts = (evtRes.events || []).filter(e => e.event_type);
  const running = daemons.filter(d => d.status === 'running');
  const alerts = evts.filter(e => e.event_type === 'daemon.alert');
  const css = [
    '.sw{display:grid;grid-template-columns:1fr 300px;height:calc(100vh - 60px);overflow:hidden}',
    '.sw-c{position:relative;background:radial-gradient(ellipse at 50% 50%,#0a0f1a,#050508);overflow:hidden;border-right:1px solid var(--border)}',
    '.sw-c canvas{position:absolute;inset:0;width:100%;height:100%}',
    '.sw-hud{position:absolute;top:16px;left:16px;right:16px;display:flex;justify-content:space-between;align-items:flex-start;z-index:10;pointer-events:none}',
    '.sw-title{font-family:IBM Plex Mono,monospace;font-size:10px;letter-spacing:3px;color:var(--mint);background:rgba(0,0,0,.7);padding:8px 14px;border:1px solid rgba(0,255,170,.15);border-radius:6px}',
    '.sw-mm{display:flex;gap:8px}',
    '.sw-m{background:rgba(0,0,0,.7);border:1px solid rgba(255,255,255,.06);border-radius:6px;padding:8px 12px;text-align:center}',
    '.sw-mv{font-size:18px;font-weight:700;color:var(--mint);font-family:IBM Plex Mono,monospace;line-height:1}',
    '.sw-ml{font-size:9px;color:var(--text3);letter-spacing:1px;text-transform:uppercase;margin-top:2px}',
    '.sw-s{display:flex;flex-direction:column;background:var(--bg2);overflow:hidden}',
    '.sw-tabs{display:flex;border-bottom:1px solid var(--border)}',
    '.sw-tab{flex:1;padding:11px;text-align:center;font-size:11px;font-weight:600;color:var(--text3);cursor:pointer;border-bottom:2px solid transparent;transition:all .2s}',
    '.sw-tab.active{color:var(--mint);border-bottom-color:var(--mint)}',
    '.sw-p{flex:1;overflow-y:auto;padding:14px;display:none}',
    '.sw-p.active{display:block}',
    '.sw-p::-webkit-scrollbar{width:3px}.sw-p::-webkit-scrollbar-thumb{background:var(--border)}',
    '.dnc{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:13px;margin-bottom:9px;cursor:pointer;transition:all .2s;position:relative;overflow:hidden}',
    '.dnc::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--mint)}',
    '.dnc:hover{border-color:rgba(0,255,170,.2);transform:translateX(2px)}',
    '.dnc-h{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}',
    '.dnc-n{font-size:13px;font-weight:600}.dnc-s{font-size:9px;letter-spacing:1.5px;color:var(--mint);font-family:IBM Plex Mono,monospace}',
    '.dnc-t{font-size:11px;color:var(--text3);line-height:1.5;margin-bottom:7px}',
    '.dnc-m{display:flex;gap:10px;font-size:10px;color:var(--text3);font-family:IBM Plex Mono,monospace}',
    '.dnc-stop{position:absolute;top:10px;right:10px;background:rgba(255,60,90,.1);border:1px solid rgba(255,60,90,.2);color:var(--rose);font-size:10px;padding:2px 7px;border-radius:4px;cursor:pointer}',
    '.ei{display:flex;gap:9px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.03)}',
    '.ed{width:6px;height:6px;border-radius:50%;flex-shrink:0;margin-top:5px}',
    '.eb{flex:1;min-width:0}',
    '.et{display:flex;align-items:center;gap:5px;margin-bottom:2px}',
    '.en{font-size:11px;font-weight:600;color:var(--text)}.ety{font-size:9px;color:var(--text3);font-family:IBM Plex Mono,monospace}',
    '.em{font-size:11px;color:var(--text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.etm{font-size:9px;color:var(--text3);font-family:IBM Plex Mono,monospace;margin-top:1px}',
    '.dep-btn{width:100%;padding:13px;background:var(--mint);color:#04040a;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;margin-bottom:12px}'
  ].join('');

  let workersHtml = `<button class="dep-btn" onclick="swarmDeploy()">+ Deploy Worker</button>`;
  if (running.length) {
    running.forEach(d => {
      workersHtml += `<div class="dnc" onclick="swarmFocus('${d.daemon_id}')">
        <button class="dnc-stop" onclick="event.stopPropagation();stopDaemon('${d.daemon_id}')">Stop</button>
        <div class="dnc-h"><div class="dnc-n">${d.agent_name}</div><div class="dnc-s">&#9679; LIVE</div></div>
        <div class="dnc-t">${(d.task||'').slice(0,80)}</div>
        <div class="dnc-m"><span>Cycle ${d.cycles||0}</span><span>Every ${d.interval_seconds}s</span></div>
        </div>`;
    });
  } else {
    workersHtml += `<div style="text-align:center;padding:40px 16px;color:var(--text3)"><div style="font-size:36px;margin-bottom:10px;opacity:.3">&#11041;</div><div style="font-size:12px">No active workers</div></div>`;
  }

  let feedHtml = evts.length ? '' : `<div style="text-align:center;padding:40px;color:var(--text3);font-size:12px">No activity yet</div>`;
  evts.slice().reverse().slice(0,30).forEach(e => {
    const col = e.event_type.includes('alert') ? 'var(--amber)' : e.event_type.includes('fail') ? 'var(--rose)' : 'var(--mint)';
    feedHtml += `<div class="ei"><div class="ed" style="background:${col}"></div><div class="eb">
      <div class="et"><span class="en">${e.agent_name||'system'}</span><span class="ety">${e.event_type}</span></div>
      <div class="em">${(e.message||'').slice(0,100)}</div>
      <div class="etm">${new Date(e.timestamp||e.created_at).toLocaleTimeString()}</div>
      </div></div>`;
  });

  let alertsHtml = alerts.length ? '' : `<div style="text-align:center;padding:40px;color:var(--text3);font-size:12px">No alerts &#10003;</div>`;
  alerts.slice().reverse().forEach(e => {
    alertsHtml += `<div style="background:rgba(255,180,0,.04);border:1px solid rgba(255,180,0,.12);border-radius:8px;padding:11px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="font-size:12px;font-weight:600;color:var(--amber)">${e.agent_name}</span>
      <span style="font-size:10px;color:var(--text3)">${new Date(e.timestamp||e.created_at).toLocaleTimeString()}</span></div>
      <div style="font-size:11px;color:var(--text2)">${(e.message||'').slice(0,150)}</div></div>`;
  });

  const completedCount = evts.filter(e => e.event_type === 'agent.completed').length;
  $('#main').innerHTML = `<div class="page fade-up" style="padding:0"><style>${css}</style>
    <div class="sw">
      <div class="sw-c"><canvas id="swarmCanvas"></canvas>
        <div class="sw-hud"><div class="sw-title">&#11041; LIVE SWARM</div>
          <div class="sw-mm">
            <div class="sw-m"><div class="sw-mv">${running.length}</div><div class="sw-ml">Active</div></div>
            <div class="sw-m"><div class="sw-mv" style="color:var(--amber)">${alerts.length}</div><div class="sw-ml">Alerts</div></div>
            <div class="sw-m"><div class="sw-mv" style="color:var(--violet)">${completedCount}</div><div class="sw-ml">Done</div></div>
          </div></div></div>
      <div class="sw-s">
        <div class="sw-tabs">
          <div class="sw-tab active" onclick="swarmTab('workers',this)">Workers</div>
          <div class="sw-tab" onclick="swarmTab('feed',this)">Feed</div>
          <div class="sw-tab" onclick="swarmTab('alerts',this)">Alerts</div>
        </div>
        <div class="sw-p active" id="sw-workers">${workersHtml}</div>
        <div class="sw-p" id="sw-feed">${feedHtml}</div>
        <div class="sw-p" id="sw-alerts">${alertsHtml}</div>
      </div>
    </div></div>`;

  initSwarmCanvas(running, evts);
  setTimeout(() => { if(page==='swarm') pSwarm(); }, 15000);
}

function swarmTab(name, el) {
  document.querySelectorAll('.sw-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.sw-p').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('sw-'+name).classList.add('active');
}

function swarmFocus(id) {
  if(window._swarmNodes) window._swarmNodes.forEach(n=>{n.focused=(n.id===id);});
}

function initSwarmCanvas(daemons, events) {
  const canvas = document.getElementById('swarmCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth||800, H = canvas.offsetHeight||600;
  canvas.width = W; canvas.height = H;
  const cx = W/2, cy = H/2, orbitR = Math.min(W,H)*.28;
  const HUB = {id:'hub',x:cx,y:cy,r:26,color:'#00ffaa',label:'APEX',type:'hub',pulse:0};
  const nodes = [HUB];
  daemons.forEach((d,i) => {
    const a = (i/Math.max(daemons.length,1))*Math.PI*2-Math.PI/2;
    nodes.push({id:d.daemon_id,x:cx+Math.cos(a)*(orbitR+(Math.random()-.5)*40),y:cy+Math.sin(a)*(orbitR+(Math.random()-.5)*40),r:15,color:d.cycles>5?'#00ffaa':'#a374ff',label:(d.agent_name||'').split(' ')[0],type:'daemon',pulse:Math.random()*Math.PI*2,vx:(Math.random()-.5)*.3,vy:(Math.random()-.5)*.3,focused:false});
  });
  window._swarmNodes = nodes;
  const particles = [];
  let frame = 0;
  function draw() {
    ctx.clearRect(0,0,W,H); frame++;
    ctx.strokeStyle='rgba(0,255,170,.03)'; ctx.lineWidth=1;
    for(let x=0;x<W;x+=60){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
    for(let y=0;y<H;y+=60){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
    nodes.filter(n=>n.type==='daemon').forEach(n=>{
      const g=ctx.createLinearGradient(HUB.x,HUB.y,n.x,n.y);
      g.addColorStop(0,'rgba(0,255,170,.2)'); g.addColorStop(1,'rgba(0,255,170,.03)');
      ctx.strokeStyle=g; ctx.lineWidth=1; ctx.setLineDash([4,8]); ctx.lineDashOffset=-frame*.5;
      ctx.beginPath(); ctx.moveTo(HUB.x,HUB.y); ctx.lineTo(n.x,n.y); ctx.stroke(); ctx.setLineDash([]);
    });
    for(let i=particles.length-1;i>=0;i--) {
      const p=particles[i]; p.progress+=p.speed;
      if(p.progress>=1){particles.splice(i,1);continue;}
      ctx.globalAlpha=Math.sin(p.progress*Math.PI); ctx.fillStyle='#00ffaa';
      ctx.beginPath(); ctx.arc(p.x+(p.tx-p.x)*p.progress, p.y+(p.ty-p.y)*p.progress, 2.5,0,Math.PI*2); ctx.fill(); ctx.globalAlpha=1;
    }
    nodes.forEach(n=>{
      n.pulse+=.04;
      if(n.type==='daemon'){
        n.x+=n.vx; n.y+=n.vy;
        const dx=n.x-cx,dy=n.y-cy,dist=Math.sqrt(dx*dx+dy*dy);
        if(dist>orbitR+60){n.vx*=-.5;n.vy*=-.5;} if(dist<orbitR-60){n.vx+=dx*.001;n.vy+=dy*.001;}
        n.vx*=.99; n.vy*=.99;
      }
      const gr=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,n.r*3);
      gr.addColorStop(0,n.color==='#00ffaa'?'rgba(0,255,170,.12)':'rgba(163,116,255,.12)'); gr.addColorStop(1,'transparent');
      ctx.fillStyle=gr; ctx.beginPath(); ctx.arc(n.x,n.y,n.r*3,0,Math.PI*2); ctx.fill();
      if(n.type==='hub'||n.focused){ctx.strokeStyle=n.color+'33';ctx.lineWidth=1;ctx.beginPath();ctx.arc(n.x,n.y,n.r+10+Math.sin(n.pulse)*5,0,Math.PI*2);ctx.stroke();}
      ctx.fillStyle=n.type==='hub'?'#04040a':'#0a0f1a'; ctx.strokeStyle=n.focused?'#fff':n.color; ctx.lineWidth=n.focused?2:1.5;
      ctx.beginPath(); ctx.arc(n.x,n.y,n.r,0,Math.PI*2); ctx.fill(); ctx.stroke();
      ctx.fillStyle=n.color; ctx.font=n.type==='hub'?'bold 9px IBM Plex Mono':'8px IBM Plex Mono'; ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText(n.type==='hub'?'APEX':n.label.slice(0,4).toUpperCase(),n.x,n.y);
      if(n.type==='daemon'){ctx.fillStyle=n.focused?'#fff':'rgba(255,255,255,.45)';ctx.font='8px sans-serif';ctx.fillText(n.label.slice(0,10),n.x,n.y+n.r+10);}
    });
    if(frame%90===0&&nodes.length>1){const s=nodes[1+Math.floor(Math.random()*(nodes.length-1))];particles.push({x:s.x,y:s.y,tx:HUB.x,ty:HUB.y,progress:0,speed:.015+Math.random()*.01});}
    if(frame%130===0&&nodes.length>1){const s=nodes[1+Math.floor(Math.random()*(nodes.length-1))];particles.push({x:HUB.x,y:HUB.y,tx:s.x,ty:s.y,progress:0,speed:.015+Math.random()*.01});}
    requestAnimationFrame(draw);
  }
  draw();
}

function swarmTab(name, el) {
  document.querySelectorAll('.swarm-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.swarm-panel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('swarm-'+name).classList.add('active');
}

function swarmFocusNode(id) {
  if(window._swarmNodes) window._swarmNodes.forEach(n => { n.focused = (n.id === id); });
}

function initSwarmCanvas(daemons, events) {
  const canvas = document.getElementById('swarmCanvas');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth||800, H = canvas.offsetHeight||600;
  canvas.width = W; canvas.height = H;
  const cx = W/2, cy = H/2;
  const orbitR = Math.min(W,H)*0.28;
  const nodes = [{id:'hub',x:cx,y:cy,r:28,color:'#00ffaa',label:'APEX',type:'hub',pulse:0,vx:0,vy:0}];
  daemons.forEach((d,i) => {
    const angle = (i/Math.max(daemons.length,1))*Math.PI*2-Math.PI/2;
    nodes.push({id:d.daemon_id,x:cx+Math.cos(angle)*(orbitR+(Math.random()-.5)*40),y:cy+Math.sin(angle)*(orbitR+(Math.random()-.5)*40),r:16,color:d.cycles>5?'#00ffaa':'#a374ff',label:d.agent_name.split(' ')[0],type:'daemon',daemon:d,pulse:Math.random()*Math.PI*2,vx:(Math.random()-.5)*.3,vy:(Math.random()-.5)*.3,focused:false});
  });
  window._swarmNodes = nodes;
  const HUB = nodes[0];
  const particles = [];
  let frame = 0;
  function draw() {
    ctx.clearRect(0,0,W,H);
    frame++;
    ctx.strokeStyle='rgba(0,255,170,0.03)';ctx.lineWidth=1;
    for(let x=0;x<W;x+=60){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke()}
    for(let y=0;y<H;y+=60){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke()}
    nodes.filter(n=>n.type==='daemon').forEach(n=>{
      const grad=ctx.createLinearGradient(HUB.x,HUB.y,n.x,n.y);
      grad.addColorStop(0,'rgba(0,255,170,0.25)');grad.addColorStop(1,'rgba(0,255,170,0.04)');
      ctx.strokeStyle=grad;ctx.lineWidth=1;ctx.setLineDash([4,8]);ctx.lineDashOffset=-frame*.5;
      ctx.beginPath();ctx.moveTo(HUB.x,HUB.y);ctx.lineTo(n.x,n.y);ctx.stroke();ctx.setLineDash([]);
    });
    for(let i=particles.length-1;i>=0;i--){
      const p=particles[i];p.progress+=p.speed;
      if(p.progress>=1){particles.splice(i,1);continue}
      const x=p.x+(p.tx-p.x)*p.progress,y=p.y+(p.ty-p.y)*p.progress;
      ctx.globalAlpha=Math.sin(p.progress*Math.PI);ctx.fillStyle='#00ffaa';
      ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;
    }
    nodes.forEach(n=>{
      n.pulse+=0.04;
      if(n.type==='daemon'){
        n.x+=n.vx;n.y+=n.vy;
        const dx=n.x-cx,dy=n.y-cy,dist=Math.sqrt(dx*dx+dy*dy);
        if(dist>orbitR+60){n.vx*=-.5;n.vy*=-.5}
        if(dist<orbitR-60){n.vx+=dx*.001;n.vy+=dy*.001}
        n.vx*=.99;n.vy*=.99;
      }
      const gR=n.r+8+Math.sin(n.pulse)*4;
      const glow=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,gR*2.5);
      glow.addColorStop(0,n.color==='#00ffaa'?'rgba(0,255,170,0.15)':'rgba(163,116,255,0.15)');glow.addColorStop(1,'transparent');
      ctx.fillStyle=glow;ctx.beginPath();ctx.arc(n.x,n.y,gR*2.5,0,Math.PI*2);ctx.fill();
      if(n.type==='hub'||n.focused){ctx.strokeStyle=n.color+'44';ctx.lineWidth=1;ctx.beginPath();ctx.arc(n.x,n.y,n.r+12+Math.sin(n.pulse)*6,0,Math.PI*2);ctx.stroke()}
      ctx.fillStyle=n.type==='hub'?'#04040a':'#0a0f1a';ctx.strokeStyle=n.focused?'#fff':n.color;ctx.lineWidth=n.focused?2:1.5;
      ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,Math.PI*2);ctx.fill();ctx.stroke();
      ctx.fillStyle=n.color;ctx.font=n.type==='hub'?'bold 10px IBM Plex Mono':'9px IBM Plex Mono';ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillText(n.type==='hub'?'APEX':n.label.slice(0,4).toUpperCase(),n.x,n.y);
      if(n.type==='daemon'){ctx.fillStyle=n.focused?'#fff':'rgba(255,255,255,0.5)';ctx.font='9px sans-serif';ctx.fillText(n.label.slice(0,12),n.x,n.y+n.r+12)}
    });
    if(frame%90===0&&daemons.length){const src=nodes[1+Math.floor(Math.random()*(nodes.length-1))];if(src)particles.push({x:src.x,y:src.y,tx:HUB.x,ty:HUB.y,progress:0,speed:.015+Math.random()*.01})}
    if(frame%120===0&&daemons.length){const src=nodes[1+Math.floor(Math.random()*(nodes.length-1))];if(src)particles.push({x:HUB.x,y:HUB.y,tx:src.x,ty:src.y,progress:0,speed:.015+Math.random()*.01})}
    requestAnimationFrame(draw);
  }
  draw();
}

async function pAdmin() {
  const [usersRes, evtRes, daemonRes] = await Promise.all([
    api('/api/v1/admin/users'),
    api('/api/v1/events?limit=100'),
    api('/api/v1/daemons')
  ]);
  const users = usersRes.users || [];
  const evts = evtRes.events || [];
  const daemons = daemonRes.daemons || [];
  const totalAlerts = evts.filter(e=>e.event_type==='daemon.alert').length;
  const tiers = {free:0,starter:0,pro:0,enterprise:0};
  users.forEach(u => { tiers[u.tier||'free'] = (tiers[u.tier||'free']||0)+1; });
  const mrr = (tiers.starter*49)+(tiers.pro*199)+(tiers.enterprise*999);

  $('#main').innerHTML = '<div class="page fade-up">'
    + '<style>'
    + '.admin-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}'
    + '.admin-stat{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:20px;position:relative;overflow:hidden}'
    + '.admin-stat::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:var(--mint)}'
    + '.admin-stat.amber::before{background:var(--amber)}.admin-stat.violet::before{background:var(--violet)}.admin-stat.rose::before{background:var(--rose)}'
    + '.admin-stat-val{font-size:32px;font-weight:700;letter-spacing:-1px;margin-bottom:4px}'
    + '.admin-stat-label{font-size:11px;color:var(--text3);letter-spacing:.5px;text-transform:uppercase}'
    + '.admin-table{width:100%;border-collapse:collapse;font-size:13px}'
    + '.admin-table th{padding:10px 14px;text-align:left;font-size:10px;letter-spacing:1.5px;color:var(--text3);text-transform:uppercase;border-bottom:1px solid var(--border);font-weight:500}'
    + '.admin-table td{padding:12px 14px;border-bottom:1px solid rgba(255,255,255,0.03);color:var(--text2)}'
    + '.admin-table tr:hover td{background:rgba(255,255,255,0.02)}'
    + '.tier-pill{display:inline-block;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:600;letter-spacing:.5px;font-family:"IBM Plex Mono",monospace}'
    + '.tier-free{background:rgba(255,255,255,0.06);color:var(--text3)}.tier-starter{background:rgba(96,165,250,0.1);color:#60a5fa}.tier-pro{background:rgba(163,116,255,0.1);color:var(--violet)}.tier-enterprise{background:rgba(0,255,170,0.08);color:var(--mint)}'
    + '.admin-action{background:none;border:1px solid var(--border);color:var(--text3);font-size:10px;padding:3px 8px;border-radius:4px;cursor:pointer;font-family:"IBM Plex Mono",monospace;transition:all .2s}'
    + '.admin-action:hover{border-color:var(--text2);color:var(--text)}.admin-action.danger:hover{border-color:var(--rose);color:var(--rose)}'
    + '</style>'
    + '<div class="page-header"><div class="page-title">&#9881; Admin</div><div class="page-subtitle">' + users.length + ' users &middot; $' + mrr.toLocaleString() + ' MRR</div></div>'
    + '<div class="admin-grid">'
    + '<div class="admin-stat"><div class="admin-stat-val" style="color:var(--mint)">' + users.length + '</div><div class="admin-stat-label">Total Users</div></div>'
    + '<div class="admin-stat amber"><div class="admin-stat-val" style="color:var(--amber)">$' + mrr.toLocaleString() + '</div><div class="admin-stat-label">MRR</div></div>'
    + '<div class="admin-stat violet"><div class="admin-stat-val" style="color:var(--violet)">' + daemons.length + '</div><div class="admin-stat-label">Daemons</div></div>'
    + '<div class="admin-stat rose"><div class="admin-stat-val" style="color:var(--rose)">' + totalAlerts + '</div><div class="admin-stat-label">Alerts</div></div>'
    + '</div>'
    + '<div class="card"><div class="card-head"><div class="card-title">Users</div>'
    + '<div style="font-size:11px;color:var(--text3);font-family:\'IBM Plex Mono\',monospace;display:flex;gap:12px">'
    + '<span>Free: ' + tiers.free + '</span><span style="color:#60a5fa">Starter: ' + tiers.starter + '</span><span style="color:var(--violet)">Pro: ' + tiers.pro + '</span><span style="color:var(--mint)">Ent: ' + tiers.enterprise + '</span>'
    + '</div></div>'
    + '<div style="overflow-x:auto"><table class="admin-table"><thead><tr><th>Email</th><th>Tier</th><th>Joined</th><th>Status</th><th>Actions</th></tr></thead><tbody>'
    + (users.length ? users.slice(0,50).map(u =>
        '<tr><td style="color:var(--text)">' + u.email + '</td>'
        + '<td><span class="tier-pill tier-' + (u.tier||'free') + '">' + (u.tier||'FREE').toUpperCase() + '</span></td>'
        + '<td>' + (u.created_at ? new Date(u.created_at).toLocaleDateString() : '—') + '</td>'
        + '<td><span style="color:' + (u.active!==0?'var(--mint)':'var(--rose)') + '">&#9679; ' + (u.active!==0?'Active':'Suspended') + '</span></td>'
        + '<td style="display:flex;gap:6px"><button class="admin-action" onclick="adminUpgrade(\'' + u.id + '\',\'pro\')">&#8593; Pro</button>'
        + '<button class="admin-action danger" onclick="adminSuspend(\'' + u.id + '\')">Suspend</button></td></tr>').join('')
      : '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--text3)">No users yet</td></tr>')
    + '</tbody></table></div></div></div>';
}

async function adminUpgrade(userId, tier) {
  const r = await api('/api/v1/admin/users/'+userId+'/tier', {method:'POST', body:JSON.stringify({tier})});
  pAdmin();
}
async function adminSuspend(userId) {
  if(!confirm('Suspend this user?')) return;
  await api('/api/v1/admin/users/'+userId+'/suspend', {method:'POST'});
  pAdmin();
}

async function startDaemon() {
  const preset = prompt('Enter preset ID (e.g. crypto-monitor):');
  if (!preset) return;
  const r = await api('/api/v1/daemons', {method:'POST', body: JSON.stringify({preset_id: preset})});
  if (r.daemon_id) { alert('Worker deployed: ' + r.name); pSwarm(); }
  else alert('Error: ' + (r.detail || JSON.stringify(r)));
}

async function configureSlack() {
  const webhook = prompt('Enter your Slack Webhook URL:');
  if (!webhook) return;
  const channel = prompt('Enter channel (e.g. #ai-workforce):', '#ai-workforce');
  const r = await api('/api/v1/slack/configure', {method:'POST', body: JSON.stringify({webhook_url: webhook, channel: channel})});
  if (r.status === 'configured') {
    // Test it
    await api('/api/v1/slack/test', {method:'POST', body: JSON.stringify({webhook_url: webhook})});
    alert('✅ Slack configured! Check your channel for a test message.');
    pSwarm();
  }
}

async function stopDaemon(id) {
  await api('/api/v1/daemons/'+id,{method:'DELETE'});
  pSwarm();
}

async function pTeam() {
  $('#main').innerHTML = '<div class="page fade-up">'
    + '<div class="page-header"><div class="page-title">&#9712; Team</div><div class="page-subtitle">Manage org access and team members</div></div>'
    + '<div class="g2">'
    + '<div class="card"><div class="card-head"><div class="card-title">Create Organization</div></div><div class="card-body">'
    + '<label class="lbl">Org Name</label><input class="input" id="oName" placeholder="Acme Corp"><br>'
    + '<label class="lbl">Slug</label><input class="input" id="oSlug" placeholder="acme-corp"><br>'
    + '<label class="lbl">Owner Email</label><input class="input" id="oEmail" placeholder="admin@acme.com"><br>'
    + '<label class="lbl">Slack Webhook (optional)</label><input class="input" id="oSlack" placeholder="https://hooks.slack.com/..."><br>'
    + '<button class="btn btn-mint" style="margin-top:12px" onclick="createOrg()">Create</button>'
    + '<div id="orgRes" style="margin-top:12px;font-size:12px;color:var(--mint)"></div></div></div>'
    + '<div class="card"><div class="card-head"><div class="card-title">Invite Team Member</div></div><div class="card-body">'
    + '<label class="lbl">Org ID</label><input class="input" id="iOrg" placeholder="org-id"><br>'
    + '<label class="lbl">Email</label><input class="input" id="iEmail" placeholder="teammate@acme.com"><br>'
    + '<label class="lbl">Role</label><select class="input" id="iRole"><option value="member">Member</option><option value="admin">Admin</option><option value="viewer">Viewer</option></select><br>'
    + '<button class="btn btn-mint" style="margin-top:12px" onclick="inviteMember()">Send Invite</button>'
    + '<div id="invRes" style="margin-top:12px;font-size:12px;color:var(--mint)"></div></div></div>'
    + '</div>'
    + '<div class="card" style="margin-top:16px"><div class="card-head"><div class="card-title">Accept Invite</div></div><div class="card-body" style="display:flex;gap:12px;flex-wrap:wrap">'
    + '<input class="input" id="aTok" placeholder="Invite token" style="flex:1;min-width:180px">'
    + '<input class="input" id="aEmail" placeholder="Your email" style="flex:1;min-width:180px">'
    + '<button class="btn btn-mint" onclick="acceptInvite()">Accept</button></div>'
    + '<div id="accRes" style="padding:0 20px 16px;font-size:12px;color:var(--mint)"></div></div>'
    + '</div>';
}

async function createOrg() {
  const r = await api('/api/v1/orgs',{method:'POST',body:JSON.stringify({name:$('#oName').value,slug:$('#oSlug').value,owner_email:$('#oEmail').value,slack_webhook:$('#oSlack').value})});
  $('#orgRes').innerHTML = r.org_id ? "Created! Org ID: "+r.org_id+"<br>API Key: "+r.owner_api_key : "Error: "+(r.detail||JSON.stringify(r));
  if(r.org_id) $('#iOrg').value = r.org_id;
}

async function inviteMember() {
  const r = await api('/api/v1/orgs/'+$('#iOrg').value+'/invite',{method:'POST',body:JSON.stringify({email:$('#iEmail').value,role:$('#iRole').value})});
  $('#invRes').innerHTML = r.invite_url ? 'Invite URL: <a href="'+r.invite_url+'" style="color:var(--mint)">'+r.invite_url+'</a>' : "Error: "+(r.detail||JSON.stringify(r));
}

async function acceptInvite() {
  const r = await api('/api/v1/orgs/accept-invite',{method:'POST',body:JSON.stringify({token:$('#aTok').value,email:$('#aEmail').value})});
  $('#accRes').textContent = r.api_key ? "API Key: "+r.api_key : "Error: "+(r.detail||JSON.stringify(r));
}

function filterAudit(q){document.querySelectorAll('.ar').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?"":"none");}

async function pAudit() {
  const r = await api('/api/v1/audit/logs?limit=100');
  const logs = r.logs || [];
  const ac = a => a.includes("fail")||a.includes("error")?"var(--rose)":a.includes("login")||a.includes("signup")?"var(--mint)":"var(--amber)";
  const rows = logs.map(l =>
    '<tr style="border-bottom:1px solid rgba(255,255,255,0.03)" class="ar">'
    + '<td style="padding:9px 14px;color:var(--text3);font-family:monospace;font-size:11px">' + new Date(l.ts).toLocaleString() + '</td>'
    + '<td style="padding:9px 14px;color:var(--text2);font-size:12px">' + (l.user||"—") + '</td>'
    + '<td style="padding:9px 14px"><span style="color:' + ac(l.action) + ';font-weight:600;font-size:12px">' + l.action + '</span></td>'
    + '<td style="padding:9px 14px;color:var(--text2);font-size:12px">' + (l.resource||"—") + '</td>'
    + '<td style="padding:9px 14px;color:var(--text3);font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (l.detail||"—") + '</td>'
    + '</tr>'
  ).join("");
  $('#main').innerHTML = '<div class="page fade-up">'
    + '<div class="page-header"><div class="page-title">&#9677; Audit Log</div><div class="page-subtitle">' + logs.length + ' events</div></div>'
    + '<div class="card"><div class="card-head"><div class="card-title">Activity</div>'
    + '<input class="input" id="af" placeholder="Filter..." style="width:180px;font-size:12px" oninput="filterAudit(this.value)">'
    + '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">'
    + '<thead><tr style="border-bottom:1px solid var(--border);color:var(--text3);font-size:10px;letter-spacing:1px;text-transform:uppercase">'
    + '<th style="padding:10px 14px;text-align:left">Time</th><th style="padding:10px 14px;text-align:left">User</th><th style="padding:10px 14px;text-align:left">Action</th><th style="padding:10px 14px;text-align:left">Resource</th><th style="padding:10px 14px;text-align:left">Detail</th></tr></thead>'
    + '<tbody>' + (rows || '<tr><td colspan="5" style="text-align:center;padding:40px;color:var(--text3)">No audit events yet</td></tr>') + '</tbody></table></div></div></div>';
}

async function pBilling() {
  const r = await api('/api/v1/billing/status').catch(()=>({tier:"free",limits:{}}));
  const tiers = [
    {id:"starter",name:"Starter",price:"$49",agents:25,daemons:1,desc:"For individuals"},
    {id:"pro",name:"Pro",price:"$199",agents:100,daemons:5,desc:"For growing teams",hot:true},
    {id:"enterprise",name:"Enterprise",price:"$999",agents:"Unlimited",daemons:50,desc:"Full AI workforce"},
  ];
  const cards = tiers.map(t =>
    '<div class="card" style="' + (t.hot?"border-color:var(--mint);":r.tier===t.id?"border-color:var(--violet);":"") + '">'
    + '<div class="card-body" style="text-align:center;padding:28px 20px">'
    + (r.tier===t.id?'<div style="font-size:10px;color:var(--violet);letter-spacing:2px;margin-bottom:8px">CURRENT</div>':"")
    + (t.hot?'<div style="font-size:10px;color:var(--mint);letter-spacing:2px;margin-bottom:8px">MOST POPULAR</div>':"")
    + '<div style="font-size:20px;font-weight:700;margin-bottom:6px">' + t.name + '</div>'
    + '<div style="font-size:36px;font-weight:800;color:var(--mint)">' + t.price + '<span style="font-size:14px;color:var(--text3)">/mo</span></div>'
    + '<div style="font-size:12px;color:var(--text3);margin:8px 0 16px">' + t.desc + '</div>'
    + '<div style="font-size:12px;color:var(--text2);text-align:left;margin-bottom:16px">'
    + '<div style="margin-bottom:4px">&#10003; ' + t.agents + ' agent runs/day</div>'
    + '<div style="margin-bottom:4px">&#10003; ' + t.daemons + ' background workers</div>'
    + '<div>&#10003; Telegram + Slack alerts</div></div>'
    + (r.tier===t.id
      ? '<button class="btn" style="width:100%;opacity:0.4" disabled>Current Plan</button>'
      : '<button class="btn btn-mint" style="width:100%" onclick="upgradePlan(\''+ t.id +'\')">' + (r.tier==="free"?"Upgrade to ":"Switch to ") + t.name + '</button>')
    + '</div></div>'
  ).join("");
  $('#main').innerHTML = '<div class="page fade-up">'
    + '<div class="page-header"><div class="page-title">&#9672; Billing</div>'
    + '<div class="page-subtitle">Current: <strong style="color:var(--mint)">' + (r.tier||"free").toUpperCase() + '</strong></div></div>'
    + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">' + cards + '</div></div>';
}

async function upgradePlan(tier) {
  const r = await api('/api/v1/billing/checkout',{method:'POST',body:JSON.stringify({tier})});
  if(r.checkout_url) window.location.href=r.checkout_url;
  else alert("Contact sales@apexswarm.ai to upgrade");
}

async function stopDaemon(id) {
  await api('/api/v1/daemons/'+id,{method:'DELETE'});
  pSwarm();
}

async function pTeam() {
  $('#main').innerHTML = '<div class="page fade-up">'
    + '<div class="page-header"><div class="page-title">&#9712; Team</div><div class="page-subtitle">Manage org access and team members</div></div>'
    + '<div class="g2">'
    + '<div class="card"><div class="card-head"><div class="card-title">Create Organization</div></div><div class="card-body">'
    + '<label class="lbl">Org Name</label><input class="input" id="oName" placeholder="Acme Corp"><br>'
    + '<label class="lbl">Slug</label><input class="input" id="oSlug" placeholder="acme-corp"><br>'
    + '<label class="lbl">Owner Email</label><input class="input" id="oEmail" placeholder="admin@acme.com"><br>'
    + '<label class="lbl">Slack Webhook (optional)</label><input class="input" id="oSlack" placeholder="https://hooks.slack.com/..."><br>'
    + '<button class="btn btn-mint" style="margin-top:12px" onclick="createOrg()">Create</button>'
    + '<div id="orgRes" style="margin-top:12px;font-size:12px;color:var(--mint)"></div></div></div>'
    + '<div class="card"><div class="card-head"><div class="card-title">Invite Team Member</div></div><div class="card-body">'
    + '<label class="lbl">Org ID</label><input class="input" id="iOrg" placeholder="org-id"><br>'
    + '<label class="lbl">Email</label><input class="input" id="iEmail" placeholder="teammate@acme.com"><br>'
    + '<label class="lbl">Role</label><select class="input" id="iRole"><option value="member">Member</option><option value="admin">Admin</option><option value="viewer">Viewer</option></select><br>'
    + '<button class="btn btn-mint" style="margin-top:12px" onclick="inviteMember()">Send Invite</button>'
    + '<div id="invRes" style="margin-top:12px;font-size:12px;color:var(--mint)"></div></div></div>'
    + '</div>'
    + '<div class="card" style="margin-top:16px"><div class="card-head"><div class="card-title">Accept Invite</div></div><div class="card-body" style="display:flex;gap:12px;flex-wrap:wrap">'
    + '<input class="input" id="aTok" placeholder="Invite token" style="flex:1;min-width:180px">'
    + '<input class="input" id="aEmail" placeholder="Your email" style="flex:1;min-width:180px">'
    + '<button class="btn btn-mint" onclick="acceptInvite()">Accept</button></div>'
    + '<div id="accRes" style="padding:0 20px 16px;font-size:12px;color:var(--mint)"></div></div>'
    + '</div>';
}

async function createOrg() {
  const r = await api('/api/v1/orgs',{method:'POST',body:JSON.stringify({name:$('#oName').value,slug:$('#oSlug').value,owner_email:$('#oEmail').value,slack_webhook:$('#oSlack').value})});
  $('#orgRes').innerHTML = r.org_id ? "Created! Org ID: "+r.org_id+"<br>API Key: "+r.owner_api_key : "Error: "+(r.detail||JSON.stringify(r));
  if(r.org_id) $('#iOrg').value = r.org_id;
}

async function inviteMember() {
  const r = await api('/api/v1/orgs/'+$('#iOrg').value+'/invite',{method:'POST',body:JSON.stringify({email:$('#iEmail').value,role:$('#iRole').value})});
  $('#invRes').innerHTML = r.invite_url ? 'Invite URL: <a href="'+r.invite_url+'" style="color:var(--mint)">'+r.invite_url+'</a>' : "Error: "+(r.detail||JSON.stringify(r));
}

async function acceptInvite() {
  const r = await api('/api/v1/orgs/accept-invite',{method:'POST',body:JSON.stringify({token:$('#aTok').value,email:$('#aEmail').value})});
  $('#accRes').textContent = r.api_key ? "API Key: "+r.api_key : "Error: "+(r.detail||JSON.stringify(r));
}

function filterAudit(q){document.querySelectorAll('.ar').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?"":"none");}

async function pAudit() {
  const r = await api('/api/v1/audit/logs?limit=100');
  const logs = r.logs || [];
  const ac = a => a.includes("fail")||a.includes("error")?"var(--rose)":a.includes("login")||a.includes("signup")?"var(--mint)":"var(--amber)";
  const rows = logs.map(l =>
    '<tr style="border-bottom:1px solid rgba(255,255,255,0.03)" class="ar">'
    + '<td style="padding:9px 14px;color:var(--text3);font-family:monospace;font-size:11px">' + new Date(l.ts).toLocaleString() + '</td>'
    + '<td style="padding:9px 14px;color:var(--text2);font-size:12px">' + (l.user||"—") + '</td>'
    + '<td style="padding:9px 14px"><span style="color:' + ac(l.action) + ';font-weight:600;font-size:12px">' + l.action + '</span></td>'
    + '<td style="padding:9px 14px;color:var(--text2);font-size:12px">' + (l.resource||"—") + '</td>'
    + '<td style="padding:9px 14px;color:var(--text3);font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (l.detail||"—") + '</td>'
    + '</tr>'
  ).join("");
  $('#main').innerHTML = '<div class="page fade-up">'
    + '<div class="page-header"><div class="page-title">&#9677; Audit Log</div><div class="page-subtitle">' + logs.length + ' events</div></div>'
    + '<div class="card"><div class="card-head"><div class="card-title">Activity</div>'
    + '<input class="input" id="af" placeholder="Filter..." style="width:180px;font-size:12px" oninput="filterAudit(this.value)">'
    + '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">'
    + '<thead><tr style="border-bottom:1px solid var(--border);color:var(--text3);font-size:10px;letter-spacing:1px;text-transform:uppercase">'
    + '<th style="padding:10px 14px;text-align:left">Time</th><th style="padding:10px 14px;text-align:left">User</th><th style="padding:10px 14px;text-align:left">Action</th><th style="padding:10px 14px;text-align:left">Resource</th><th style="padding:10px 14px;text-align:left">Detail</th></tr></thead>'
    + '<tbody>' + (rows || '<tr><td colspan="5" style="text-align:center;padding:40px;color:var(--text3)">No audit events yet</td></tr>') + '</tbody></table></div></div></div>';
}

async function pBilling() {
  const r = await api('/api/v1/billing/status').catch(()=>({tier:"free",limits:{}}));
  const tiers = [
    {id:"starter",name:"Starter",price:"$49",agents:25,daemons:1,desc:"For individuals"},
    {id:"pro",name:"Pro",price:"$199",agents:100,daemons:5,desc:"For growing teams",hot:true},
    {id:"enterprise",name:"Enterprise",price:"$999",agents:"Unlimited",daemons:50,desc:"Full AI workforce"},
  ];
  const cards = tiers.map(t =>
    '<div class="card" style="' + (t.hot?"border-color:var(--mint);":r.tier===t.id?"border-color:var(--violet);":"") + '">'
    + '<div class="card-body" style="text-align:center;padding:28px 20px">'
    + (r.tier===t.id?'<div style="font-size:10px;color:var(--violet);letter-spacing:2px;margin-bottom:8px">CURRENT</div>':"")
    + (t.hot?'<div style="font-size:10px;color:var(--mint);letter-spacing:2px;margin-bottom:8px">MOST POPULAR</div>':"")
    + '<div style="font-size:20px;font-weight:700;margin-bottom:6px">' + t.name + '</div>'
    + '<div style="font-size:36px;font-weight:800;color:var(--mint)">' + t.price + '<span style="font-size:14px;color:var(--text3)">/mo</span></div>'
    + '<div style="font-size:12px;color:var(--text3);margin:8px 0 16px">' + t.desc + '</div>'
    + '<div style="font-size:12px;color:var(--text2);text-align:left;margin-bottom:16px">'
    + '<div style="margin-bottom:4px">&#10003; ' + t.agents + ' agent runs/day</div>'
    + '<div style="margin-bottom:4px">&#10003; ' + t.daemons + ' background workers</div>'
    + '<div>&#10003; Telegram + Slack alerts</div></div>'
    + (r.tier===t.id
      ? '<button class="btn" style="width:100%;opacity:0.4" disabled>Current Plan</button>'
      : '<button class="btn btn-mint" style="width:100%" onclick="upgradePlan(\''+ t.id +'\')">' + (r.tier==="free"?"Upgrade to ":"Switch to ") + t.name + '</button>')
    + '</div></div>'
  ).join("");
  $('#main').innerHTML = '<div class="page fade-up">'
    + '<div class="page-header"><div class="page-title">&#9672; Billing</div>'
    + '<div class="page-subtitle">Current: <strong style="color:var(--mint)">' + (r.tier||"free").toUpperCase() + '</strong></div></div>'
    + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">' + cards + '</div></div>';
}

async function upgradePlan(tier) {
  const r = await api('/api/v1/billing/checkout',{method:'POST',body:JSON.stringify({tier})});
  if(r.checkout_url) window.location.href=r.checkout_url;
  else alert("Contact sales@apexswarm.ai to upgrade");
}

async function pDaemons() {
  const r=await api('/api/v1/daemons');
  const daemons=r.daemons||[];const presets=r.presets||{};
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Daemons</div><div class="page-subtitle">24/7 autonomous monitors</div></div>
    <div class="g3" style="margin-bottom:20px">${Object.entries(presets).map(([id,p])=>`<div class="card" style="cursor:pointer" onclick="startDaemon('${id}')"><div class="card-body"><div style="font-weight:600;font-size:14px;margin-bottom:4px">${p.name}</div><div style="color:var(--text2);font-size:12px">${(p.task_description||'').slice(0,60)}</div><div style="margin-top:8px;font-size:11px;color:var(--text3)">Every ${p.interval_seconds}s</div></div></div>`).join('')}</div>
    <div class="card"><div class="card-head"><div class="card-title">Running</div></div><div class="card-body">${daemons.map(d=>`<div class="agent-row"><div class="dot ${d.status==='running'?'live':'err'}"></div><div class="agent-info"><div class="agent-name">${d.agent_name}</div><div class="agent-task">${d.cycles} cycles</div></div><button class="btn btn-sm" style="color:var(--rose)" onclick="stopDaemon('${d.daemon_id}')">Stop</button></div>`).join('')||'<div style="text-align:center;padding:20px;color:var(--text3)">No daemons running</div>'}</div></div></div>`;
}
async function startDaemon(id){await api('/api/v1/daemons',{method:'POST',body:JSON.stringify({preset_id:id})});pDaemons();}
async function stopDaemon(id){await api('/api/v1/daemons/'+id,{method:'DELETE'});pDaemons();}

// ─── WORKFLOWS ──────────────────────────
async function pWorkflows() {
  const [w,t]=await Promise.all([api('/api/v1/workflows'),api('/api/v1/workflows/templates')]);
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Workflows</div></div>
    <div class="g3" style="margin-bottom:20px">${Object.entries(t.templates||{}).map(([id,tp])=>`<div class="card" style="cursor:pointer" onclick="createWF('${id}')"><div class="card-body"><div style="font-weight:600;margin-bottom:4px">${tp.name}</div><div style="color:var(--text2);font-size:12px">${tp.description||''}</div></div></div>`).join('')}</div>
    <div class="card"><div class="card-head"><div class="card-title">Active</div></div><div class="card-body">${(w.workflows||[]).map(wf=>`<div class="agent-row"><div class="dot ${wf.enabled?'live':'idle'}"></div><div class="agent-info"><div class="agent-name">${wf.name}</div><div class="agent-task">${wf.trigger_type} · ${wf.fire_count} fires</div></div><button class="btn btn-sm" onclick="toggleWF('${wf.workflow_id}')">Toggle</button></div>`).join('')||'<div style="text-align:center;padding:20px;color:var(--text3)">No workflows</div>'}</div></div></div>`;
}
async function createWF(id){await api('/api/v1/workflows',{method:'POST',body:JSON.stringify({template_id:id})});pWorkflows();}
async function toggleWF(id){await api('/api/v1/workflows/'+id+'/toggle',{method:'POST'});pWorkflows();}

// ─── MARKETPLACE ──────────────────────────
async function pMarketplace() {
  const [ag,ft,cat]=await Promise.all([api('/api/v1/marketplace/agents'),api('/api/v1/marketplace/featured'),api('/api/v1/marketplace/categories')]);
  const starters=ft.starters||[];const items=ag.agents||[];
  const all=[...items,...(items.length===0?starters.map((s,i)=>({...s,agent_id:'s'+i,slug:'s'+i,is_free:true,install_count:0,avg_rating:0,creator:'APEX Team'})):[])];
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Agent Marketplace</div><div class="page-subtitle">Discover, install, and deploy community agents</div></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px"><button class="btn btn-sm" style="border-color:var(--mint);color:var(--mint)" onclick="pMarketplace()">All</button>${(cat.categories||[]).map(c=>`<button class="btn btn-sm">${c.icon} ${c.name}</button>`).join('')}</div>
    <div class="g3">${all.map(a=>`<div class="mp-card" onclick="viewMp('${a.slug||a.agent_id}')"><div class="mp-card-icon">${a.icon||'◈'}</div><div class="mp-card-name">${a.name}</div><div class="mp-card-desc">${a.description}</div><div class="mp-card-footer"><span class="mp-price">${a.is_free||!a.price_usd?'FREE':'$'+a.price_usd}</span><span>⬡ ${a.install_count||0}</span></div></div>`).join('')}</div></div>`;
}
async function viewMp(slug) {
  const a=await api('/api/v1/marketplace/agents/'+slug);if(!a||a.error)return;
  const o=document.createElement('div');o.className='modal-bg';o.onclick=e=>{if(e.target===o)o.remove()};
  o.innerHTML=`<div class="modal-box"><div style="font-size:40px;margin-bottom:12px">${a.icon||'◈'}</div><div style="font-size:20px;font-weight:700;margin-bottom:8px">${a.name}</div><div style="color:var(--text2);margin-bottom:16px">${a.description}</div><div style="display:flex;gap:16px;font-size:13px;margin-bottom:16px"><span class="mp-price" style="font-size:16px">${a.is_free?'FREE':'$'+a.price_usd}</span><span style="color:var(--text3)">⬡ ${a.install_count} installs</span></div><button class="btn btn-mint" onclick="installMp('${a.agent_id}',this)">Install</button> <button class="btn" onclick="this.closest('.modal-bg').remove()">Close</button><div id="mpRes" style="margin-top:12px"></div></div>`;
  document.body.appendChild(o);
}
async function installMp(id,b){b.innerHTML='<div class="spin"></div>';const r=await api('/api/v1/marketplace/agents/'+id+'/install',{method:'POST'});b.innerHTML='Install';$('#mpRes').innerHTML=r.install_id?'<div style="color:var(--mint)">✓ Installed</div>':`<div style="color:var(--rose)">${r.detail||'Failed'}</div>`;}

// ─── MODELS ──────────────────────────
async function pModels() {
  const r=await api('/api/v1/models');
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">AI Models</div><div class="page-subtitle">${r.available_count||1} providers connected · ${r.total_models||3} models available</div></div>
    ${(r.providers||[]).map(p=>`<div class="card" style="margin-bottom:14px"><div class="card-head"><div class="card-title"><div class="dot ${p.available?'live':'idle'}"></div>${p.name}</div>${!p.available?`<span style="font-size:11px;color:var(--text3)">Add API key to enable</span>`:''}</div>${p.available?`<div class="card-body"><div class="g3">${p.models.map(m=>`<div style="background:var(--bg);padding:12px;border-radius:10px"><div style="font-weight:500;font-size:13px">${m.name}${m.vision?' 👁':''}</div><div style="font-size:11px;color:var(--text3);margin-top:4px">${m.context_window?.toLocaleString()||'?'} ctx · $${m.cost_per_1m_input}/M</div></div>`).join('')}</div></div>`:''}</div>`).join('')}</div>`;
}

// ─── ORG CHART ──────────────────────────
async function pTeam() {
  $('#main').innerHTML = `<div class="page fade-up">
    <div class="page-header">
      <div class="page-title">◰ Team</div>
      <div class="page-subtitle">Manage your AI workforce team and access</div>
    </div>
    <div class="g2">
      <div class="card">
        <div class="card-head">
          <div class="card-title">Create Organization</div>
        </div>
        <div class="card-body">
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Org Name</label>
            <input class="input" id="orgName" placeholder="Acme Corp" style="margin-top:6px">
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Slug</label>
            <input class="input" id="orgSlug" placeholder="acme-corp" style="margin-top:6px">
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Owner Email</label>
            <input class="input" id="orgEmail" placeholder="admin@acme.com" style="margin-top:6px">
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Slack Webhook (optional)</label>
            <input class="input" id="orgSlack" placeholder="https://hooks.slack.com/..." style="margin-top:6px">
          </div>
          <button class="btn btn-mint" onclick="createOrg()">Create Organization</button>
          <div id="orgResult" style="margin-top:12px;font-size:12px;color:var(--mint)"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title">Invite Team Member</div>
        </div>
        <div class="card-body">
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Org ID</label>
            <input class="input" id="inviteOrgId" placeholder="org-id from creation" style="margin-top:6px">
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Email</label>
            <input class="input" id="inviteEmail" placeholder="teammate@acme.com" style="margin-top:6px">
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Role</label>
            <select class="input" id="inviteRole" style="margin-top:6px">
              <option value="member">Member</option>
              <option value="admin">Admin</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>
          <button class="btn btn-mint" onclick="inviteMember()">Send Invite</button>
          <div id="inviteResult" style="margin-top:12px;font-size:12px;color:var(--mint)"></div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-head"><div class="card-title">Accept Invite</div></div>
      <div class="card-body" style="display:flex;gap:12px;flex-wrap:wrap">
        <input class="input" id="inviteToken" placeholder="Invite token" style="flex:1;min-width:200px">
        <input class="input" id="acceptEmail" placeholder="Your email" style="flex:1;min-width:200px">
        <button class="btn btn-mint" onclick="acceptInvite()">Accept & Get API Key</button>
      </div>
      <div id="acceptResult" style="margin-top:12px;font-size:12px;color:var(--mint);padding:0 20px 16px"></div>
    </div>
  </div>`;
}

async function createOrg() {
  const name = $('#orgName').value.trim();
  const slug = $('#orgSlug').value.trim();
  const email = $('#orgEmail').value.trim();
  const slack = $('#orgSlack').value.trim();
  if (!name || !slug || !email) { alert('Fill in org name, slug, and email'); return; }
  const r = await api('/api/v1/orgs', {method:'POST', body: JSON.stringify({name, slug, owner_email: email, slack_webhook: slack})});
  if (r.org_id) {
    $('#orgResult').innerHTML = `✅ Created! <br>Org ID: <code>${r.org_id}</code><br>Your API Key: <code>${r.owner_api_key}</code>`;
    $('#inviteOrgId').value = r.org_id;
  } else {
    $('#orgResult').textContent = 'Error: ' + (r.detail || JSON.stringify(r));
  }
}

async function inviteMember() {
  const org_id = $('#inviteOrgId').value.trim();
  const email = $('#inviteEmail').value.trim();
  const role = $('#inviteRole').value;
  if (!org_id || !email) { alert('Fill in org ID and email'); return; }
  const r = await api('/api/v1/orgs/' + org_id + '/invite', {method:'POST', body: JSON.stringify({email, role})});
  if (r.invite_url) {
    $('#inviteResult').innerHTML = `✅ Invite sent!<br>URL: <a href="${r.invite_url}" style="color:var(--mint)">${r.invite_url}</a>`;
  } else {
    $('#inviteResult').textContent = 'Error: ' + (r.detail || JSON.stringify(r));
  }
}

async function acceptInvite() {
  const token = $('#inviteToken').value.trim();
  const email = $('#acceptEmail').value.trim();
  if (!token || !email) { alert('Fill in token and email'); return; }
  const r = await api('/api/v1/orgs/accept-invite', {method:'POST', body: JSON.stringify({token, email})});
  if (r.api_key) {
    $('#acceptResult').innerHTML = `✅ Welcome! Your API Key: <code style="background:var(--bg2);padding:4px 8px;border-radius:4px">${r.api_key}</code><br>Save this — it won't be shown again.`;
  } else {
    $('#acceptResult').textContent = 'Error: ' + (r.detail || JSON.stringify(r));
  }
}

async function pOrg() {
  const r=await api('/api/v1/roles');
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">Organization Chart</div><div class="page-subtitle">Role-based agent permissions and capabilities</div></div>
    <div class="g3">${(r.roles||[]).map(ro=>`<div class="org-node"><div class="org-icon">${ro.icon}</div><div class="org-role">${ro.name}</div><div class="org-tools">${ro.tool_count} tools${ro.can_delegate?' · Can Delegate':''}</div><div style="margin-top:8px;font-size:11px;color:var(--text3)">${ro.description}</div></div>`).join('')}</div></div>`;
}

// ─── SETTINGS ──────────────────────────
async function pSettings() {
  const [h,m]=await Promise.all([api('/api/v1/health'),api('/api/v1/channels')]);
  $('#main').innerHTML=`<div class="page fade-up"><div class="page-header"><div class="page-title">System</div></div>
    <div class="g2">
      <div class="card"><div class="card-head"><div class="card-title">Info</div></div><div class="card-body" style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--text2);line-height:2.2">
        Version: ${h.version||'?'}<br>Database: ${h.database||'?'}<br>Auth: ${h.auth||'?'}<br>API: ${BASE}
      </div></div>
      <div class="card"><div class="card-head"><div class="card-title">Channels</div></div><div class="card-body">${Object.entries(m||{}).map(([n,i])=>`<div class="agent-row"><div class="dot ${i.enabled?'live':'idle'}"></div><div class="agent-name" style="text-transform:capitalize">${n}</div><span class="agent-badge ${i.enabled?'badge-done':'badge-err'}">${i.enabled?'Connected':'Off'}</span></div>`).join('')}</div></div>
    </div>
    <div class="card" style="margin-top:14px"><div class="card-head"><div class="card-title">API Key</div></div><div class="card-body"><input class="input" id="sKey" value="${KEY}" style="font-family:'IBM Plex Mono',monospace;font-size:12px"><button class="btn btn-mint btn-sm" style="margin-top:10px" onclick="KEY=$('#sKey').value;localStorage.setItem('apex_key',KEY)">Save</button></div></div></div>`;
}

// ─── SSE ──────────────────────────
function connectSSE() {
  if(sse)sse.close();
  sse=new EventSource(BASE+'/api/v1/events/stream');
  sse.onmessage=e=>{try{const d=JSON.parse(e.data);if(d.event_type){events.push(d);if(events.length>200)events.shift();if(page==='feed')pFeed();if(page==='overview'){const f=$('#overviewFeed');if(f)f.innerHTML=events.slice(-6).reverse().map(ev=>`<div class="event-item"><div class="event-dot" style="background:var(--mint)"></div><div class="event-content">${ev.agent_name||ev.agent_type||'—'}<div class="event-time">${new Date(ev.timestamp).toLocaleTimeString()}</div></div></div>`).join('');}}}catch(x){}};
  sse.onerror=()=>{$('.pulse-dot').style.background='var(--rose)';$('.sidebar-status span').textContent='Offline';setTimeout(connectSSE,5000)};
  sse.onopen=()=>{$('.pulse-dot').style.background='var(--mint)';$('.sidebar-status span').textContent='Live'};
}

// ─── INIT ──────────────────────────
const TOKEN = localStorage.getItem('apex_token') || "";
function signOut() {
  fetch('/api/v1/auth/logout',{method:'POST',headers:{'X-Session-Token':TOKEN}});
  localStorage.removeItem('apex_token');
  localStorage.removeItem('apex_key');
  localStorage.removeItem('apex_email');
  window.location.href='/login';
}
connectSSE();
go('overview');
</script>
</body>
</html>
"""


# ─── ENTRYPOINT ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
