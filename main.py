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
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
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
            ]
            for table, col, col_type in migration_columns:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    conn.commit()
                    logger.info(f"✅ Migration: added {table}.{col}")
                except Exception:
                    pass  # Column already exists
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



@app.get("/api/v1/daemons/status")
async def get_daemon_status(api_key: str = Depends(verify_api_key)):
    """
    Returns live status of all daemons.
    Shows: id, preset_id, status, last_run, next_run, run_count, last_error
    """
    try:
        daemons = daemon_manager.daemons if hasattr(daemon_manager, "daemons") else {}
        now = datetime.utcnow()

        result = []
        for daemon_id, d in daemons.items():
            interval = d.get("interval_seconds", 0)
            last_run = d.get("last_run")
            next_run = None
            if last_run and interval:
                try:
                    lr = datetime.fromisoformat(last_run) if isinstance(last_run, str) else last_run
                    next_run = (lr + timedelta(seconds=interval)).isoformat()
                except Exception:
                    pass

            result.append({
                "daemon_id": daemon_id,
                "preset_id": d.get("preset_id", "custom"),
                "agent_type": d.get("agent_type"),
                "status": d.get("status", "unknown"),
                "interval_seconds": interval,
                "run_count": d.get("run_count", 0),
                "last_run": last_run,
                "next_run_estimated": next_run,
                "last_error": d.get("last_error"),
            })

        # Flag any boot daemons that are missing entirely
        running_presets = {r["preset_id"] for r in result}
        missing = [p for p in BOOT_DAEMONS if p not in running_presets]

        return {
            "total_daemons": len(result),
            "running": sum(1 for r in result if r["status"] == "running"),
            "stopped": sum(1 for r in result if r["status"] != "running"),
            "missing_boot_daemons": missing,
            "daemons": result,
            "checked_at": now.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


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
async def landing_page():
    return HTMLResponse(LANDING_HTML.replace("__VERSION__", VERSION))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML.replace("__VERSION__", VERSION))




SWARM_VIEW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX SWARM — Live Swarm View</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#050508;--surface:#0e0e18;--surface2:#141422;
  --border:rgba(255,255,255,0.06);
  --text:#f0f0f8;--text2:#8888a8;--text3:#555570;
  --mint:#00f0a0;--mintglow:rgba(0,240,160,0.25);
  --cyan:#00d4ff;--cyanglow:rgba(0,212,255,0.2);
  --amber:#ffb800;--amberglow:rgba(255,184,0,0.2);
  --rose:#ff3366;--roseglow:rgba(255,51,102,0.2);
  --violet:#7733ff;--violetglow:rgba(119,51,255,0.2);
}
body{background:var(--bg);color:var(--text);font-family:'Instrument Sans',sans-serif;overflow:hidden;height:100vh}

/* ─── LAYOUT ─── */
.container{display:grid;grid-template-columns:1fr 340px;grid-template-rows:56px 1fr;height:100vh}
.topbar{grid-column:1/-1;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 24px}
.canvas-area{position:relative;overflow:hidden}
.sidebar{background:var(--surface);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}

/* ─── TOPBAR ─── */
.top-title{font-weight:700;font-size:15px;display:flex;align-items:center;gap:10px}
.top-title .pulse{width:8px;height:8px;border-radius:50%;background:var(--mint);box-shadow:0 0 12px var(--mintglow);animation:breathe 2s ease infinite}
@keyframes breathe{0%,100%{opacity:1}50%{opacity:0.4}}
.top-stats{display:flex;gap:24px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--text2)}
.top-stats span{color:var(--mint);font-weight:600}
.top-back{color:var(--text2);font-size:13px;cursor:pointer;text-decoration:none;display:flex;align-items:center;gap:6px}
.top-back:hover{color:var(--mint)}

/* ─── CANVAS ─── */
.canvas-area canvas{display:block}
.canvas-overlay{position:absolute;bottom:20px;left:20px;display:flex;gap:12px}
.legend-item{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text3)}
.legend-dot{width:8px;height:8px;border-radius:50%}

/* ─── SIDEBAR TABS ─── */
.side-tabs{display:flex;border-bottom:1px solid var(--border)}
.side-tab{flex:1;padding:12px;text-align:center;font-size:12px;font-weight:500;color:var(--text3);cursor:pointer;border-bottom:2px solid transparent;transition:all 0.2s}
.side-tab:hover{color:var(--text)}
.side-tab.active{color:var(--mint);border-bottom-color:var(--mint)}
.side-content{flex:1;overflow-y:auto;padding:12px}

/* ─── AGENT ITEMS ─── */
.agent-item{padding:10px 12px;border-radius:10px;margin-bottom:6px;cursor:pointer;transition:all 0.2s;border:1px solid transparent}
.agent-item:hover{background:rgba(255,255,255,0.02);border-color:var(--border)}
.agent-item.selected{background:var(--surface2);border-color:var(--border)}
.agent-item-header{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.agent-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.agent-item-name{font-weight:600;font-size:13px;flex:1}
.agent-item-badge{font-family:'IBM Plex Mono',monospace;font-size:9px;padding:2px 6px;border-radius:4px;font-weight:600;text-transform:uppercase}
.agent-item-task{font-size:11.5px;color:var(--text2);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

/* ─── EVENT LOG ─── */
.event-log-item{padding:8px 0;border-bottom:1px solid var(--border);font-size:12px;display:flex;gap:8px}
.event-log-item:last-child{border:none}
.event-log-time{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text3);white-space:nowrap;min-width:55px}
.event-log-msg{color:var(--text2);line-height:1.4}
.event-log-msg strong{color:var(--text);font-weight:500}

/* ─── DETAIL PANEL ─── */
.detail-panel{padding:16px;border-top:1px solid var(--border);background:var(--surface2)}
.detail-title{font-weight:700;font-size:14px;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.detail-field{font-size:12px;color:var(--text2);margin-bottom:4px}
.detail-field span{color:var(--text)}
.detail-result{margin-top:8px;padding:10px;background:var(--bg);border-radius:8px;font-size:12px;max-height:150px;overflow-y:auto;white-space:pre-wrap;line-height:1.5;color:var(--text2)}
</style>
</head>
<body>

<div class="container">
  <!-- TOP BAR -->
  <div class="topbar">
    <a href="/dashboard" class="top-back">← Command Center</a>
    <div class="top-title"><div class="pulse"></div> Live Swarm View</div>
    <div class="top-stats">
      <div>Active: <span id="statActive">0</span></div>
      <div>Events: <span id="statEvents">0</span></div>
      <div>Daemons: <span id="statDaemons">0</span></div>
    </div>
  </div>

  <!-- CANVAS -->
  <div class="canvas-area">
    <canvas id="swarmCanvas"></canvas>
    <div class="canvas-overlay">
      <div class="legend-item"><div class="legend-dot" style="background:var(--mint)"></div> Running</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--cyan)"></div> Completed</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--rose)"></div> Failed</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--amber)"></div> Daemon</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--violet)"></div> Delegating</div>
    </div>
  </div>

  <!-- SIDEBAR -->
  <div class="sidebar">
    <div class="side-tabs">
      <div class="side-tab active" onclick="switchTab('agents')">Agents</div>
      <div class="side-tab" onclick="switchTab('events')">Events</div>
      <div class="side-tab" onclick="switchTab('daemons')">Daemons</div>
    </div>
    <div class="side-content" id="sideContent"></div>
    <div class="detail-panel" id="detailPanel" style="display:none"></div>
  </div>
</div>

<script>
const BASE = location.origin;
const KEY = localStorage.getItem('apex_key') || '';
let nodes = [];
let connections = [];
let events = [];
let selectedNode = null;
let sseEvents = [];
let currentTab = 'agents';
let canvas, ctx, W, H;
let animFrame;
let mouseX = 0, mouseY = 0;

// ─── API ─────────────────────────
async function api(p) {
  try {
    const r = await fetch(BASE + p, { headers: { 'X-Api-Key': KEY } });
    return await r.json();
  } catch(e) { return {}; }
}

// ─── CANVAS SETUP ────────────────
function initCanvas() {
  canvas = document.getElementById('swarmCanvas');
  ctx = canvas.getContext('2d');
  resize();
  window.addEventListener('resize', resize);
  canvas.addEventListener('mousemove', e => { mouseX = e.offsetX; mouseY = e.offsetY; });
  canvas.addEventListener('click', handleClick);
}

function resize() {
  const area = canvas.parentElement;
  W = area.clientWidth;
  H = area.clientHeight;
  canvas.width = W * devicePixelRatio;
  canvas.height = H * devicePixelRatio;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.scale(devicePixelRatio, devicePixelRatio);
  // Reposition nodes
  nodes.forEach(n => {
    if (n.x > W) n.x = Math.random() * W * 0.8 + W * 0.1;
    if (n.y > H) n.y = Math.random() * H * 0.8 + H * 0.1;
  });
}

// ─── NODE MANAGEMENT ─────────────
const COLORS = {
  running: { fill: '#00f0a0', glow: 'rgba(0,240,160,0.3)', ring: 'rgba(0,240,160,0.15)' },
  completed: { fill: '#00d4ff', glow: 'rgba(0,212,255,0.2)', ring: 'rgba(0,212,255,0.1)' },
  failed: { fill: '#ff3366', glow: 'rgba(255,51,102,0.2)', ring: 'rgba(255,51,102,0.1)' },
  daemon: { fill: '#ffb800', glow: 'rgba(255,184,0,0.2)', ring: 'rgba(255,184,0,0.1)' },
  delegating: { fill: '#7733ff', glow: 'rgba(119,51,255,0.3)', ring: 'rgba(119,51,255,0.15)' },
};

const ICONS = {
  'research': '🔬', 'crypto-research': '💎', 'market-analyst': '📊', 'blog-writer': '✍️',
  'social-media': '📣', 'code-reviewer': '💻', 'data-analyst': '📈', 'seo-specialist': '🎯',
  'copywriter': '✏️', 'defi-analyst': '🏦', 'macro-analyst': '🌐', 'pitch-deck': '📋',
  'summarizer': '📝', 'api-designer': '🔧', 'legal-analyst': '⚖️',
};

function addNode(agent) {
  // Check if already exists
  const existing = nodes.find(n => n.id === agent.id);
  if (existing) {
    existing.status = agent.status;
    existing.result = agent.result;
    return existing;
  }

  const padding = 80;
  const n = {
    id: agent.id,
    type: agent.agent_type || agent.type || 'research',
    name: agent.agent_type || agent.type || 'agent',
    task: agent.task_description || agent.task || '',
    status: agent.status || 'running',
    result: agent.result || '',
    x: padding + Math.random() * (W - padding * 2),
    y: padding + Math.random() * (H - padding * 2),
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
    radius: agent.status === 'daemon' ? 22 : 16,
    pulsePhase: Math.random() * Math.PI * 2,
    born: Date.now(),
  };
  nodes.push(n);

  // Keep max 50 nodes
  if (nodes.length > 50) nodes.shift();

  return n;
}

function addConnection(fromId, toId, type = 'delegate') {
  connections.push({ from: fromId, to: toId, type, born: Date.now(), alpha: 1 });
}

// ─── RENDER LOOP ─────────────────
function render() {
  ctx.clearRect(0, 0, W, H);
  const t = Date.now() / 1000;

  // Draw grid
  ctx.strokeStyle = 'rgba(255,255,255,0.015)';
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 60) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y < H; y += 60) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

  // Draw connections
  connections.forEach((c, i) => {
    const from = nodes.find(n => n.id === c.from);
    const to = nodes.find(n => n.id === c.to);
    if (!from || !to) return;

    const age = (Date.now() - c.born) / 1000;
    c.alpha = Math.max(0, 1 - age / 8); // Fade over 8s

    if (c.alpha <= 0) { connections.splice(i, 1); return; }

    // Animated dashed line
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const dashOffset = (t * 40) % 20;

    ctx.strokeStyle = `rgba(119,51,255,${c.alpha * 0.4})`;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 8]);
    ctx.lineDashOffset = -dashOffset;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrow head
    const angle = Math.atan2(dy, dx);
    const arrowX = to.x - Math.cos(angle) * (to.radius + 8);
    const arrowY = to.y - Math.sin(angle) * (to.radius + 8);
    ctx.fillStyle = `rgba(119,51,255,${c.alpha * 0.6})`;
    ctx.beginPath();
    ctx.moveTo(arrowX, arrowY);
    ctx.lineTo(arrowX - Math.cos(angle - 0.4) * 8, arrowY - Math.sin(angle - 0.4) * 8);
    ctx.lineTo(arrowX - Math.cos(angle + 0.4) * 8, arrowY - Math.sin(angle + 0.4) * 8);
    ctx.fill();

    // "Delegating" label
    if (c.alpha > 0.5) {
      ctx.fillStyle = `rgba(119,51,255,${c.alpha * 0.5})`;
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.fillText('delegate', (from.x + to.x) / 2 - 20, (from.y + to.y) / 2 - 6);
    }
  });

  // Update and draw nodes
  nodes.forEach(n => {
    // Drift
    n.x += n.vx;
    n.y += n.vy;

    // Boundaries
    if (n.x < 40 || n.x > W - 40) n.vx *= -1;
    if (n.y < 40 || n.y > H - 40) n.vy *= -1;

    // Gentle attraction to center
    n.vx += (W / 2 - n.x) * 0.00003;
    n.vy += (H / 2 - n.y) * 0.00003;

    // Repel from other nodes
    nodes.forEach(o => {
      if (o.id === n.id) return;
      const dx = n.x - o.x;
      const dy = n.y - o.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 80) {
        const force = (80 - dist) / 80 * 0.05;
        n.vx += (dx / dist) * force;
        n.vy += (dy / dist) * force;
      }
    });

    // Damping
    n.vx *= 0.995;
    n.vy *= 0.995;

    const colors = COLORS[n.status] || COLORS.running;
    const pulse = Math.sin(t * 2 + n.pulsePhase) * 0.5 + 0.5;
    const isHovered = Math.abs(mouseX - n.x) < 30 && Math.abs(mouseY - n.y) < 30;
    const isSelected = selectedNode && selectedNode.id === n.id;

    // Outer ring (pulse for running)
    if (n.status === 'running' || n.status === 'daemon') {
      const ringR = n.radius + 8 + pulse * 6;
      ctx.fillStyle = colors.ring;
      ctx.beginPath();
      ctx.arc(n.x, n.y, ringR, 0, Math.PI * 2);
      ctx.fill();
    }

    // Selection ring
    if (isSelected) {
      ctx.strokeStyle = colors.fill;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius + 14, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Glow
    const grad = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.radius * 2.5);
    grad.addColorStop(0, colors.glow);
    grad.addColorStop(1, 'transparent');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.radius * 2.5, 0, Math.PI * 2);
    ctx.fill();

    // Node body
    ctx.fillStyle = isHovered ? colors.fill : `${colors.fill}cc`;
    ctx.beginPath();
    ctx.arc(n.x, n.y, isHovered ? n.radius + 2 : n.radius, 0, Math.PI * 2);
    ctx.fill();

    // Inner dark circle
    ctx.fillStyle = 'rgba(5,5,8,0.6)';
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.radius * 0.6, 0, Math.PI * 2);
    ctx.fill();

    // Icon
    const icon = ICONS[n.name] || '◈';
    ctx.font = `${n.radius * 0.7}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(icon, n.x, n.y);

    // Label
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = isHovered ? colors.fill : 'rgba(255,255,255,0.4)';
    ctx.textAlign = 'center';
    ctx.fillText(n.name, n.x, n.y + n.radius + 14);

    // Status label for hovered
    if (isHovered) {
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.fillText(n.status, n.x, n.y + n.radius + 26);

      // Task preview
      if (n.task) {
        ctx.font = '10px "Instrument Sans", sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.25)';
        const taskPreview = n.task.length > 40 ? n.task.slice(0, 40) + '...' : n.task;
        ctx.fillText(taskPreview, n.x, n.y + n.radius + 38);
      }
    }
  });

  // Center label when empty
  if (nodes.length === 0) {
    ctx.font = '14px "Instrument Sans", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.15)';
    ctx.textAlign = 'center';
    ctx.fillText('Deploy agents to see them here', W / 2, H / 2);
    ctx.font = '11px "IBM Plex Mono", monospace';
    ctx.fillText('Listening for activity...', W / 2, H / 2 + 24);
  }

  animFrame = requestAnimationFrame(render);
}

function handleClick(e) {
  const x = e.offsetX, y = e.offsetY;
  const clicked = nodes.find(n => Math.sqrt((n.x - x) ** 2 + (n.y - y) ** 2) < n.radius + 8);
  selectedNode = clicked || null;
  updateDetail();
  renderSidebar();
}

// ─── SIDEBAR ─────────────────────
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.side-tab').forEach(t => t.classList.toggle('active', t.textContent.toLowerCase() === tab));
  renderSidebar();
}

function renderSidebar() {
  const el = document.getElementById('sideContent');
  if (currentTab === 'agents') {
    if (nodes.length === 0) {
      el.innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--text3);font-size:13px">No agents active<br><span style="font-size:11px">Deploy from the Command Center</span></div>';
      return;
    }
    el.innerHTML = nodes.slice().reverse().map(n => {
      const colors = { running: 'var(--mint)', completed: 'var(--cyan)', failed: 'var(--rose)', daemon: 'var(--amber)' };
      const bgColors = { running: 'rgba(0,240,160,0.1)', completed: 'rgba(0,212,255,0.1)', failed: 'rgba(255,51,102,0.1)', daemon: 'rgba(255,184,0,0.1)' };
      const isSelected = selectedNode && selectedNode.id === n.id;
      return `<div class="agent-item${isSelected ? ' selected' : ''}" onclick="selectNode('${n.id}')">
        <div class="agent-item-header">
          <div class="agent-dot" style="background:${colors[n.status] || colors.running}"></div>
          <div class="agent-item-name">${ICONS[n.name] || '◈'} ${n.name}</div>
          <div class="agent-item-badge" style="background:${bgColors[n.status] || bgColors.running};color:${colors[n.status] || colors.running}">${n.status}</div>
        </div>
        <div class="agent-item-task">${n.task || 'No task description'}</div>
      </div>`;
    }).join('');
  } else if (currentTab === 'events') {
    if (sseEvents.length === 0) {
      el.innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--text3);font-size:13px">Waiting for events...</div>';
      return;
    }
    el.innerHTML = sseEvents.slice().reverse().slice(0, 50).map(e => `<div class="event-log-item">
      <div class="event-log-time">${new Date(e.timestamp).toLocaleTimeString()}</div>
      <div class="event-log-msg"><strong>${e.agent_name || e.agent_type || 'system'}</strong> ${e.message || e.event_type || ''}</div>
    </div>`).join('');
  } else if (currentTab === 'daemons') {
    const daemonNodes = nodes.filter(n => n.status === 'daemon');
    if (daemonNodes.length === 0) {
      el.innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--text3);font-size:13px">No daemons running<br><span style="font-size:11px">Start from Command Center → Daemons</span></div>';
      return;
    }
    el.innerHTML = daemonNodes.map(n => `<div class="agent-item" onclick="selectNode('${n.id}')">
      <div class="agent-item-header">
        <div class="agent-dot" style="background:var(--amber);box-shadow:0 0 8px var(--amberglow);animation:breathe 2s ease infinite"></div>
        <div class="agent-item-name">${n.name}</div>
        <div class="agent-item-badge" style="background:rgba(255,184,0,0.1);color:var(--amber)">LIVE</div>
      </div>
      <div class="agent-item-task">${n.task || 'Monitoring...'}</div>
    </div>`).join('');
  }
}

function selectNode(id) {
  selectedNode = nodes.find(n => n.id === id) || null;
  updateDetail();
  renderSidebar();
}

function updateDetail() {
  const panel = document.getElementById('detailPanel');
  if (!selectedNode) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  const n = selectedNode;
  const colors = { running: 'var(--mint)', completed: 'var(--cyan)', failed: 'var(--rose)', daemon: 'var(--amber)' };
  panel.innerHTML = `
    <div class="detail-title"><div class="agent-dot" style="background:${colors[n.status]||colors.running}"></div>${ICONS[n.name]||'◈'} ${n.name}</div>
    <div class="detail-field">Status: <span style="color:${colors[n.status]||colors.running}">${n.status}</span></div>
    <div class="detail-field">ID: <span>${n.id.slice(0, 12)}</span></div>
    ${n.task ? `<div class="detail-field">Task: <span>${n.task.slice(0, 120)}</span></div>` : ''}
    ${n.result ? `<div class="detail-result">${n.result.slice(0, 500).replace(/</g, '&lt;')}</div>` : ''}
  `;
}

// ─── DATA LOADING ────────────────
async function loadInitialData() {
  // Load recent agents
  const recent = await api('/api/v1/agents/recent?limit=20');
  (recent.agents || []).forEach(a => addNode(a));

  // Load daemons
  const daemons = await api('/api/v1/daemons');
  (daemons.daemons || []).forEach(d => {
    addNode({
      id: d.daemon_id,
      agent_type: d.agent_name || d.agent_type,
      task_description: d.task_description || `Running every ${d.interval_seconds}s`,
      status: 'daemon',
    });
  });

  // Load god-eye stats
  const ge = await api('/api/v1/god-eye');
  document.getElementById('statActive').textContent = ge.active_agents || 0;
  document.getElementById('statDaemons').textContent = ge.active_daemons || 0;

  renderSidebar();
}

// ─── SSE ─────────────────────────
function connectSSE() {
  const sse = new EventSource(BASE + '/api/v1/events/stream');
  sse.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (!data.event_type) return;

      sseEvents.push(data);
      if (sseEvents.length > 200) sseEvents.shift();
      document.getElementById('statEvents').textContent = sseEvents.length;

      // Add or update node based on event
      if (data.event_type === 'agent.started' || data.event_type === 'agent_started') {
        const node = addNode({
          id: data.agent_id,
          agent_type: data.agent_type,
          task_description: data.message,
          status: 'running',
        });
        // Flash effect
        node.radius = 24;
        setTimeout(() => { node.radius = 16; }, 500);
      }
      else if (data.event_type === 'agent.completed' || data.event_type === 'agent_completed') {
        const node = nodes.find(n => n.id === data.agent_id);
        if (node) {
          node.status = 'completed';
          node.result = data.data?.result_preview || '';
        }
      }
      else if (data.event_type === 'agent.failed' || data.event_type === 'agent_failed') {
        const node = nodes.find(n => n.id === data.agent_id);
        if (node) node.status = 'failed';
      }
      else if (data.event_type === 'daemon.alert' || data.event_type === 'daemon_alert') {
        const node = nodes.find(n => n.id === data.agent_id);
        if (node) {
          node.radius = 28;
          setTimeout(() => { node.radius = 22; }, 1000);
        }
      }

      // Update stats
      const running = nodes.filter(n => n.status === 'running').length;
      const daemonCount = nodes.filter(n => n.status === 'daemon').length;
      document.getElementById('statActive').textContent = running;
      document.getElementById('statDaemons').textContent = daemonCount;

      if (currentTab === 'events') renderSidebar();
    } catch(x) {}
  };
  sse.onerror = () => setTimeout(connectSSE, 5000);
}

// ─── INIT ────────────────────────
initCanvas();
loadInitialData();
connectSSE();
render();
</script>
</body>
</html>
"""


@app.get("/swarm", response_class=HTMLResponse)
async def swarm_view():
    return HTMLResponse(SWARM_VIEW_HTML)


LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX SWARM — Autonomous AI Agents for the Enterprise</title>
<meta name="description" content="Deploy 66+ autonomous AI agents that research, analyze, write, and execute 24/7. Multi-model, multi-channel, zero setup.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Sans:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,700;0,800;0,900;1,700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#050508;--bg2:#0a0a12;--surface:#0e0e18;--surface2:#141422;
  --border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.1);
  --text:#f0f0f8;--text2:#8888a8;--text3:#555570;
  --mint:#00f0a0;--mint2:#00cc80;--mintbg:rgba(0,240,160,0.06);--mintglow:rgba(0,240,160,0.2);
  --cyan:#00d4ff;--amber:#ffb800;--rose:#ff3366;--violet:#7733ff;
}
html{font-size:16px;scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:'Instrument Sans',sans-serif;overflow-x:hidden}
::selection{background:var(--mint);color:var(--bg)}
a{color:var(--mint);text-decoration:none}

/* ─── GRAIN ─── */
body::before{content:'';position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.025;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}

/* ─── NAV ─── */
nav{position:fixed;top:0;left:0;right:0;z-index:100;padding:18px 40px;display:flex;align-items:center;justify-content:space-between;backdrop-filter:blur(20px);background:rgba(5,5,8,0.8);border-bottom:1px solid var(--border)}
.nav-logo{font-family:'Playfair Display',serif;font-weight:900;font-size:20px;background:linear-gradient(135deg,var(--mint),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.nav-links{display:flex;gap:32px;align-items:center}
.nav-links a{color:var(--text2);font-size:14px;font-weight:500;transition:color 0.2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{background:var(--mint);color:var(--bg);padding:9px 22px;border-radius:8px;font-weight:600;font-size:13px;border:none;cursor:pointer;transition:all 0.2s}
.nav-cta:hover{background:var(--mint2);transform:translateY(-1px);box-shadow:0 4px 20px var(--mintglow)}

/* ─── HERO ─── */
.hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:120px 24px 80px;position:relative}
.hero::before{content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);width:800px;height:800px;background:radial-gradient(circle,rgba(0,240,160,0.04) 0%,transparent 70%);pointer-events:none}
.hero-badge{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:var(--mint);margin-bottom:28px;display:flex;align-items:center;gap:10px;justify-content:center}
.hero-badge::before,.hero-badge::after{content:'';width:40px;height:1px;background:linear-gradient(90deg,transparent,var(--mint))}
.hero-badge::after{background:linear-gradient(90deg,var(--mint),transparent)}
h1{font-family:'Playfair Display',serif;font-size:clamp(48px,7vw,88px);font-weight:900;line-height:1.05;letter-spacing:-2px;max-width:900px;margin-bottom:24px}
h1 em{font-style:italic;background:linear-gradient(135deg,var(--mint),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero-sub{color:var(--text2);font-size:18px;max-width:560px;line-height:1.7;margin-bottom:40px}
.hero-ctas{display:flex;gap:14px;align-items:center;flex-wrap:wrap;justify-content:center}
.btn-primary{background:var(--mint);color:var(--bg);padding:14px 32px;border-radius:10px;font-weight:700;font-size:15px;border:none;cursor:pointer;transition:all 0.25s;letter-spacing:0.3px}
.btn-primary:hover{background:var(--mint2);transform:translateY(-2px);box-shadow:0 8px 32px var(--mintglow)}
.btn-ghost{border:1px solid var(--border2);color:var(--text);padding:14px 32px;border-radius:10px;font-weight:500;font-size:15px;background:transparent;cursor:pointer;transition:all 0.2s}
.btn-ghost:hover{border-color:var(--mint);color:var(--mint)}

/* ─── LIVE TICKER ─── */
.ticker{margin-top:60px;overflow:hidden;width:100%;max-width:1000px;position:relative;height:38px;mask-image:linear-gradient(90deg,transparent,black 10%,black 90%,transparent)}
.ticker-track{display:flex;gap:40px;animation:scroll 30s linear infinite;width:max-content}
@keyframes scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.ticker-item{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--text3);white-space:nowrap;display:flex;align-items:center;gap:8px}
.ticker-dot{width:5px;height:5px;border-radius:50%;background:var(--mint);animation:blink 2s ease infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}

/* ─── STATS BAR ─── */
.stats{display:flex;justify-content:center;gap:48px;padding:60px 24px;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.stat{text-align:center}
.stat-num{font-family:'IBM Plex Mono',monospace;font-size:36px;font-weight:600;background:linear-gradient(135deg,var(--mint),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-label{font-size:12px;color:var(--text3);text-transform:uppercase;letter-spacing:2px;margin-top:6px}

/* ─── SECTIONS ─── */
section{padding:100px 24px}
.section-inner{max-width:1100px;margin:0 auto}
.section-label{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:var(--mint);margin-bottom:16px}
.section-title{font-family:'Playfair Display',serif;font-size:clamp(32px,4vw,48px);font-weight:800;letter-spacing:-1px;margin-bottom:16px;max-width:700px}
.section-desc{color:var(--text2);font-size:16px;max-width:560px;line-height:1.7;margin-bottom:48px}

/* ─── FEATURE GRID ─── */
.features{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.feature{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:28px;transition:all 0.3s;position:relative;overflow:hidden}
.feature:hover{border-color:var(--border2);transform:translateY(-3px)}
.feature::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--mint),transparent);opacity:0;transition:opacity 0.3s}
.feature:hover::before{opacity:1}
.feature-icon{font-size:28px;margin-bottom:14px}
.feature-title{font-weight:700;font-size:16px;margin-bottom:6px}
.feature-desc{color:var(--text2);font-size:13.5px;line-height:1.6}

/* ─── HOW IT WORKS ─── */
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:2px}
.step{background:var(--surface);padding:32px 24px;text-align:center;position:relative}
.step:first-child{border-radius:16px 0 0 16px}
.step:last-child{border-radius:0 16px 16px 0}
.step-num{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--mint);letter-spacing:2px;margin-bottom:12px}
.step-title{font-weight:700;font-size:15px;margin-bottom:6px}
.step-desc{color:var(--text2);font-size:13px;line-height:1.5}

/* ─── AGENTS SHOWCASE ─── */
.agents-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.agent-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;transition:all 0.2s;cursor:default}
.agent-card:hover{border-color:var(--mint)}
.agent-card-icon{font-size:24px;margin-bottom:8px}
.agent-card-name{font-weight:600;font-size:13.5px;margin-bottom:4px}
.agent-card-desc{color:var(--text3);font-size:11.5px;line-height:1.4}

/* ─── PRICING ─── */
.pricing{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.price-card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:32px;position:relative;transition:all 0.3s}
.price-card:hover{border-color:var(--border2)}
.price-card.featured{border-color:var(--mint);background:linear-gradient(180deg,rgba(0,240,160,0.03),var(--surface))}
.price-card.featured::before{content:'POPULAR';position:absolute;top:-11px;left:50%;transform:translateX(-50%);background:var(--mint);color:var(--bg);font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:2px;padding:4px 14px;border-radius:6px;font-weight:600}
.price-tier{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text3);margin-bottom:8px}
.price-amount{font-family:'Playfair Display',serif;font-size:44px;font-weight:800;margin-bottom:4px}
.price-amount span{font-size:16px;color:var(--text2);font-family:'Instrument Sans',sans-serif;font-weight:400}
.price-desc{color:var(--text2);font-size:13px;margin-bottom:24px}
.price-features{list-style:none;margin-bottom:28px}
.price-features li{padding:6px 0;font-size:13.5px;color:var(--text2);display:flex;align-items:center;gap:8px}
.price-features li::before{content:'◉';color:var(--mint);font-size:8px}
.price-btn{display:block;width:100%;text-align:center;padding:12px;border-radius:9px;font-weight:600;font-size:14px;cursor:pointer;transition:all 0.2s;border:none;font-family:'Instrument Sans',sans-serif}
.price-btn-mint{background:var(--mint);color:var(--bg)}
.price-btn-mint:hover{background:var(--mint2);box-shadow:0 4px 20px var(--mintglow)}
.price-btn-ghost{background:transparent;border:1px solid var(--border2);color:var(--text)}
.price-btn-ghost:hover{border-color:var(--mint);color:var(--mint)}

/* ─── COMPARISON ─── */
.compare-table{width:100%;border-collapse:collapse;font-size:13.5px}
.compare-table th{text-align:left;padding:12px 16px;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text3);border-bottom:1px solid var(--border)}
.compare-table td{padding:12px 16px;border-bottom:1px solid var(--border)}
.compare-table tr:hover td{background:rgba(255,255,255,0.015)}
.check{color:var(--mint)}
.cross{color:var(--text3)}

/* ─── CTA SECTION ─── */
.cta-section{text-align:center;padding:120px 24px;position:relative}
.cta-section::before{content:'';position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:600px;height:600px;background:radial-gradient(circle,rgba(0,240,160,0.05) 0%,transparent 70%);pointer-events:none}
.cta-title{font-family:'Playfair Display',serif;font-size:clamp(36px,5vw,56px);font-weight:800;letter-spacing:-1px;margin-bottom:16px}
.cta-sub{color:var(--text2);font-size:17px;margin-bottom:36px;max-width:480px;margin-left:auto;margin-right:auto}

/* ─── FOOTER ─── */
footer{border-top:1px solid var(--border);padding:40px 24px;text-align:center}
footer p{font-size:13px;color:var(--text3)}
footer a{color:var(--text2)}

/* ─── ANIMATIONS ─── */
@keyframes fadeUp{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:translateY(0)}}
.anim{opacity:0;transform:translateY(30px);transition:all 0.7s cubic-bezier(0.16,1,0.3,1)}
.anim.visible{opacity:1;transform:translateY(0)}

/* ─── RESPONSIVE ─── */
@media(max-width:900px){.features{grid-template-columns:1fr}.steps{grid-template-columns:1fr 1fr}.agents-grid{grid-template-columns:1fr 1fr}.pricing{grid-template-columns:1fr}.stats{flex-wrap:wrap;gap:24px}.nav-links a:not(.nav-cta){display:none}.step:first-child,.step:last-child{border-radius:0}.step:first-child{border-radius:16px 16px 0 0}.step:last-child{border-radius:0 0 16px 16px}}
</style>
</head>
<body>

<!-- NAV -->
<nav>
  <div class="nav-logo">APEX SWARM</div>
  <div class="nav-links">
    <a href="#features">Features</a>
    <a href="#agents">Agents</a>
    <a href="#pricing">Pricing</a>
    <a href="#compare">Compare</a>
    <a href="/dashboard" class="nav-cta">Open Dashboard →</a>
  </div>
</nav>

<!-- HERO -->
<div class="hero">
  <div class="hero-badge">Autonomous AI Platform</div>
  <h1>Your workforce<br>never <em>sleeps</em></h1>
  <p class="hero-sub">66 autonomous AI agents that research, analyze, write, and execute — 24/7. Deploy a swarm in seconds. No infrastructure. No babysitting.</p>
  <div class="hero-ctas">
    <a href="/dashboard"><button class="btn-primary">Start deploying agents →</button></a>
    <a href="#features"><button class="btn-ghost">See how it works</button></a>
  </div>

  <!-- LIVE TICKER -->
  <div class="ticker">
    <div class="ticker-track">
      <div class="ticker-item"><div class="ticker-dot"></div>crypto-research analyzing BTC market structure</div>
      <div class="ticker-item"><div class="ticker-dot"></div>blog-writer creating SEO content for fintech startup</div>
      <div class="ticker-item"><div class="ticker-dot"></div>data-analyst processing Q1 revenue metrics</div>
      <div class="ticker-item"><div class="ticker-dot"></div>market-analyst scanning emerging AI companies</div>
      <div class="ticker-item"><div class="ticker-dot"></div>defi-analyst monitoring yield farming opportunities</div>
      <div class="ticker-item"><div class="ticker-dot"></div>code-reviewer auditing smart contract security</div>
      <div class="ticker-item"><div class="ticker-dot"></div>social-media generating viral thread for product launch</div>
      <div class="ticker-item"><div class="ticker-dot"></div>competitor-intel tracking OpenClaw latest features</div>
      <div class="ticker-item"><div class="ticker-dot"></div>crypto-research analyzing BTC market structure</div>
      <div class="ticker-item"><div class="ticker-dot"></div>blog-writer creating SEO content for fintech startup</div>
      <div class="ticker-item"><div class="ticker-dot"></div>data-analyst processing Q1 revenue metrics</div>
      <div class="ticker-item"><div class="ticker-dot"></div>market-analyst scanning emerging AI companies</div>
      <div class="ticker-item"><div class="ticker-dot"></div>defi-analyst monitoring yield farming opportunities</div>
      <div class="ticker-item"><div class="ticker-dot"></div>code-reviewer auditing smart contract security</div>
      <div class="ticker-item"><div class="ticker-dot"></div>social-media generating viral thread for product launch</div>
      <div class="ticker-item"><div class="ticker-dot"></div>competitor-intel tracking OpenClaw latest features</div>
    </div>
  </div>
</div>

<!-- STATS -->
<div class="stats">
  <div class="stat"><div class="stat-num">66+</div><div class="stat-label">Specialized Agents</div></div>
  <div class="stat"><div class="stat-num">12</div><div class="stat-label">Built-in Tools</div></div>
  <div class="stat"><div class="stat-num">9</div><div class="stat-label">LLM Providers</div></div>
  <div class="stat"><div class="stat-num">24/7</div><div class="stat-label">Autonomous</div></div>
  <div class="stat"><div class="stat-num">95</div><div class="stat-label">API Endpoints</div></div>
</div>

<!-- FEATURES -->
<section id="features">
  <div class="section-inner">
    <div class="section-label anim">Capabilities</div>
    <div class="section-title anim">Not another chatbot.<br>A full operating system.</div>
    <div class="section-desc anim">Every feature designed for autonomous execution. Agents don't wait for instructions — they complete missions.</div>
    <div class="features">
      <div class="feature anim"><div class="feature-icon">◆</div><div class="feature-title">Autonomous Goals</div><div class="feature-desc">Give a business objective. The swarm builds an org chart, decomposes into projects and tasks, assigns role-based agents, and executes end-to-end.</div></div>
      <div class="feature anim"><div class="feature-icon">◇</div><div class="feature-title">Agent-to-Agent Protocol</div><div class="feature-desc">Agents hire other agents. A lead agent decomposes complex tasks, delegates to specialists, and synthesizes results into one deliverable.</div></div>
      <div class="feature anim"><div class="feature-icon">◌</div><div class="feature-title">24/7 Daemons</div><div class="feature-desc">Always-on monitors that scan markets, track competitors, watch for opportunities. Alert you on Telegram when conditions are met.</div></div>
      <div class="feature anim"><div class="feature-icon">◫</div><div class="feature-title">Agent Marketplace</div><div class="feature-desc">Create, publish, and sell custom agents. Creators earn 80% of every sale. Install community agents with one click.</div></div>
      <div class="feature anim"><div class="feature-icon">◑</div><div class="feature-title">Multi-Model Intelligence</div><div class="feature-desc">Route tasks to Claude, GPT-4o, Gemini, Llama, DeepSeek, Mistral, Grok — or your own local models. 9 providers, 30+ models.</div></div>
      <div class="feature anim"><div class="feature-icon">⬡</div><div class="feature-title">Workflow Automation</div><div class="feature-desc">Trigger → Condition → Action engine. When a daemon alerts, deploy an agent. When an agent completes, notify Slack. Chain anything.</div></div>
      <div class="feature anim"><div class="feature-icon">◰</div><div class="feature-title">Role-Based Permissions</div><div class="feature-desc">10 org chart roles — CEO, CTO, CMO, CFO, Researcher, Writer, Analyst, Marketer, Support, Security — each with scoped tool and email access.</div></div>
      <div class="feature anim"><div class="feature-icon">◎</div><div class="feature-title">Voice Interface</div><div class="feature-desc">Talk to your swarm. Voice messages transcribed via Whisper, agents respond with TTS. 14 voice options across 2 providers.</div></div>
      <div class="feature anim"><div class="feature-icon">◉</div><div class="feature-title">Enterprise Hardened</div><div class="feature-desc">Retry logic, circuit breakers, input sanitization, audit trail, metrics, conversation persistence, Swagger API docs.</div></div>
    </div>
  </div>
</section>

<!-- HOW IT WORKS -->
<section style="background:var(--bg2)">
  <div class="section-inner">
    <div class="section-label anim">How it works</div>
    <div class="section-title anim">Four steps to autonomous operations</div>
    <div class="section-desc anim">From zero to a running AI workforce in under 60 seconds.</div>
    <div class="steps anim">
      <div class="step"><div class="step-num">01</div><div class="step-title">Define a goal</div><div class="step-desc">"Monitor DeFi yields and alert me when APY exceeds 15%"</div></div>
      <div class="step"><div class="step-num">02</div><div class="step-title">Swarm decomposes</div><div class="step-desc">AI breaks it into projects, assigns roles, selects the best agents</div></div>
      <div class="step"><div class="step-num">03</div><div class="step-title">Agents execute</div><div class="step-desc">Specialists research, analyze, and monitor — using live tools and APIs</div></div>
      <div class="step"><div class="step-num">04</div><div class="step-title">Results delivered</div><div class="step-desc">Reports in your dashboard. Alerts on Telegram. Actions via webhooks.</div></div>
    </div>
  </div>
</section>

<!-- AGENTS -->
<section id="agents">
  <div class="section-inner">
    <div class="section-label anim">The Swarm</div>
    <div class="section-title anim">66 agents. 6 divisions.</div>
    <div class="section-desc anim">Each agent is a specialist. Together, they're an autonomous workforce.</div>
    <div class="agents-grid anim">
      <div class="agent-card"><div class="agent-card-icon">🔬</div><div class="agent-card-name">Deep Research</div><div class="agent-card-desc">Multi-source investigation with citations</div></div>
      <div class="agent-card"><div class="agent-card-icon">📊</div><div class="agent-card-name">Market Analyst</div><div class="agent-card-desc">Technical analysis and trend detection</div></div>
      <div class="agent-card"><div class="agent-card-icon">💎</div><div class="agent-card-name">Crypto Research</div><div class="agent-card-desc">On-chain data, DeFi protocols, alpha signals</div></div>
      <div class="agent-card"><div class="agent-card-icon">✍️</div><div class="agent-card-name">Blog Writer</div><div class="agent-card-desc">Long-form SEO content with research</div></div>
      <div class="agent-card"><div class="agent-card-icon">📣</div><div class="agent-card-name">Social Media</div><div class="agent-card-desc">Viral threads, hooks, engagement copy</div></div>
      <div class="agent-card"><div class="agent-card-icon">💻</div><div class="agent-card-name">Code Reviewer</div><div class="agent-card-desc">Security audits, refactoring, best practices</div></div>
      <div class="agent-card"><div class="agent-card-icon">📈</div><div class="agent-card-name">Data Analyst</div><div class="agent-card-desc">Metrics, dashboards, statistical analysis</div></div>
      <div class="agent-card"><div class="agent-card-icon">🎯</div><div class="agent-card-name">SEO Specialist</div><div class="agent-card-desc">Keyword research, content optimization</div></div>
    </div>
    <div style="text-align:center;margin-top:32px"><a href="/dashboard" style="color:var(--text2);font-size:14px">View all 66 agents in the dashboard →</a></div>
  </div>
</section>

<!-- PRICING -->
<section id="pricing" style="background:var(--bg2)">
  <div class="section-inner">
    <div class="section-label anim" style="text-align:center">Pricing</div>
    <div class="section-title anim" style="text-align:center;margin-left:auto;margin-right:auto">Start free. Scale to enterprise.</div>
    <div class="section-desc anim" style="text-align:center;margin-left:auto;margin-right:auto">Bring your own LLM API key. Pay only for what your agents use.</div>
    <div class="pricing anim">
      <div class="price-card">
        <div class="price-tier">Starter</div>
        <div class="price-amount">$0<span>/mo</span></div>
        <div class="price-desc">Try the swarm. Deploy agents on demand.</div>
        <ul class="price-features">
          <li>10 agent deploys / day</li>
          <li>All 66 agent types</li>
          <li>Dashboard access</li>
          <li>Telegram channel</li>
          <li>Community support</li>
        </ul>
        <button class="price-btn price-btn-ghost" onclick="location.href='/dashboard'">Get started</button>
      </div>
      <div class="price-card featured">
        <div class="price-tier">Pro</div>
        <div class="price-amount">$49<span>/mo</span></div>
        <div class="price-desc">Unlimited agents. Full autonomy.</div>
        <ul class="price-features">
          <li>Unlimited agent deploys</li>
          <li>24/7 daemons (5 concurrent)</li>
          <li>A2A delegation protocol</li>
          <li>Autonomous goals</li>
          <li>Marketplace access</li>
          <li>Voice interface</li>
          <li>Multi-model routing</li>
          <li>Priority support</li>
        </ul>
        <button class="price-btn price-btn-mint" onclick="location.href='https://apexswarm.gumroad.com/l/pro'">Start Pro trial →</button>
      </div>
      <div class="price-card">
        <div class="price-tier">Enterprise</div>
        <div class="price-amount">Custom</div>
        <div class="price-desc">For teams running AI operations at scale.</div>
        <ul class="price-features">
          <li>Everything in Pro</li>
          <li>Unlimited daemons</li>
          <li>Custom agent development</li>
          <li>Dedicated infrastructure</li>
          <li>SLA guarantee</li>
          <li>SSO / SAML</li>
          <li>Audit & compliance reports</li>
          <li>Account manager</li>
        </ul>
        <button class="price-btn price-btn-ghost" onclick="location.href='mailto:enterprise@apex-swarm.com'">Contact sales</button>
      </div>
    </div>
  </div>
</section>

<!-- COMPARE -->
<section id="compare">
  <div class="section-inner">
    <div class="section-label anim" style="text-align:center">Why APEX SWARM</div>
    <div class="section-title anim" style="text-align:center;margin-left:auto;margin-right:auto">Built different.</div>
    <div style="overflow-x:auto;margin-top:48px" class="anim">
      <table class="compare-table">
        <thead><tr><th>Capability</th><th>APEX SWARM</th><th>OpenClaw</th><th>Claude Code</th><th>ChatGPT</th></tr></thead>
        <tbody>
          <tr><td>Multi-agent orchestration</td><td class="check">◉ 66 agents + A2A</td><td class="cross">1 agent + skills</td><td class="check">Agent Teams</td><td class="cross">Single chat</td></tr>
          <tr><td>Autonomous goals</td><td class="check">◉ Goal → Org → Execute</td><td class="cross">—</td><td class="cross">—</td><td class="cross">—</td></tr>
          <tr><td>24/7 daemons</td><td class="check">◉ Always-on monitors</td><td class="check">Cron + heartbeat</td><td class="check">/loop command</td><td class="cross">—</td></tr>
          <tr><td>Agent marketplace</td><td class="check">◉ Create + sell agents</td><td class="cross">Free skills only</td><td class="check">Skills marketplace</td><td class="cross">GPT Store</td></tr>
          <tr><td>Multi-model</td><td class="check">◉ 9 providers, 30+ models</td><td class="check">Multi-provider</td><td class="cross">Claude only</td><td class="cross">GPT only</td></tr>
          <tr><td>Role-based permissions</td><td class="check">◉ 10 org chart roles</td><td class="cross">—</td><td class="cross">—</td><td class="cross">—</td></tr>
          <tr><td>Zero setup</td><td class="check">◉ Cloud API</td><td class="cross">Self-hosted</td><td class="cross">Local CLI</td><td class="check">Web app</td></tr>
          <tr><td>Voice I/O</td><td class="check">◉ STT + TTS</td><td class="check">Voice support</td><td class="check">Voice STT</td><td class="check">Voice mode</td></tr>
          <tr><td>Enterprise security</td><td class="check">◉ Audit + sanitization</td><td class="check">SecretRef + sandbox</td><td class="check">Sandboxing</td><td class="cross">—</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

<!-- CTA -->
<div class="cta-section">
  <div class="section-label">Ready?</div>
  <div class="cta-title">Deploy your first<br>agent in 30 seconds.</div>
  <div class="cta-sub">No credit card. No infrastructure. Just results.</div>
  <a href="/dashboard"><button class="btn-primary" style="font-size:17px;padding:16px 40px">Open Command Center →</button></a>
</div>

<!-- FOOTER -->
<footer>
  <p>APEX SWARM · Autonomous AI Agent Platform · <a href="/api/v1/docs">API Docs</a> · <a href="/api/v1/health">Status</a></p>
</footer>

<!-- SCROLL ANIMATIONS -->
<script>
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
    }
  });
}, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
document.querySelectorAll('.anim').forEach(el => observer.observe(el));
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

.sidebar-footer{margin-top:auto;padding:16px 24px;border-top:1px solid var(--border);display:flex;align-items:center;gap:10px}
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
      <div class="nav-btn" data-p="daemons" onclick="go('daemons')"><span class="icon">◌</span> Daemons</div>
      <div class="nav-btn" data-p="workflows" onclick="go('workflows')"><span class="icon">⬡</span> Workflows</div>
    </div>
    <div class="nav-group">
      <div class="nav-group-label">Platform</div>
      <div class="nav-btn" data-p="marketplace" onclick="go('marketplace')"><span class="icon">◫</span> Marketplace</div>
      <div class="nav-btn" data-p="models" onclick="go('models')"><span class="icon">◑</span> Models</div>
      <div class="nav-btn" data-p="org" onclick="go('org')"><span class="icon">◰</span> Org Chart</div>
      <div class="nav-btn" data-p="settings" onclick="go('settings')"><span class="icon">◎</span> System</div>
    </div>

    <div class="sidebar-footer">
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
let page = 'overview';
let events = [];
let sse = null;

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
  const R = {overview:pOverview,deploy:pDeploy,agents:pAgents,feed:pFeed,goals:pGoals,a2a:pA2A,daemons:pDaemons,workflows:pWorkflows,marketplace:pMarketplace,models:pModels,org:pOrg,settings:pSettings};
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


# ── DAEMON AUTO-START ────────────────────────────────────────────────────────
BOOT_DAEMONS = [
    "crypto-monitor",
    "defi-yield-scanner",
    "news-sentinel",
    "whale-watcher",
    "competitor-tracker",
    "competitor-intel",
]

async def autostart_daemons():
    """Auto-start all preset daemons on boot. Idempotent — skips running ones."""
    print("[BOOT] Starting daemon auto-start sequence...", flush=True)
    started = 0
    skipped = 0
    failed = 0
    for preset_id in BOOT_DAEMONS:
        try:
            # Check if already running
            already_running = any(
                d.get("preset_id") == preset_id and d.get("status") == "running"
                for d in daemon_manager.daemons.values()
            ) if hasattr(daemon_manager, "daemons") else False

            if already_running:
                print(f"[BOOT] Daemon '{preset_id}' already running — skipped", flush=True)
                skipped += 1
                continue

            # Find preset config
            preset = next((p for p in DAEMON_PRESETS if p["id"] == preset_id), None)
            if not preset:
                print(f"[BOOT] WARNING: No preset found for '{preset_id}'", flush=True)
                failed += 1
                continue

            # Start the daemon
            daemon_id = await daemon_manager.start_daemon(
                agent_type=preset["agent_type"],
                task_description=preset["task"],
                interval_seconds=preset["interval_seconds"],
                preset_id=preset_id,
            )
            print(f"[BOOT] ✅ Started '{preset_id}' → daemon_id={daemon_id} (every {preset['interval_seconds']}s)", flush=True)
            started += 1

        except Exception as e:
            print(f"[BOOT] ❌ Failed to start '{preset_id}': {e}", flush=True)
            failed += 1

    print(f"[BOOT] Daemon auto-start complete: {started} started, {skipped} skipped, {failed} failed", flush=True)
