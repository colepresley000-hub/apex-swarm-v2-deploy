"""
APEX SWARM - Agent Marketplace
================================
Users create, publish, discover, install, and sell custom agents.

Features:
  1. Custom Agent Builder — define system prompt, tools, category, model preference
  2. Marketplace — browse, search, install published agents
  3. Revenue Sharing — creators set price, platform takes 20%, creator gets 80%
  4. Ratings & Reviews — users rate installed agents
  5. Skill Packs — bundles of agents + workflows + MCP tools
  6. Version Control — publish updates, users get notified
  7. Usage Analytics — creators see how their agents perform

File: marketplace.py
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("apex-swarm")

PLATFORM_FEE = 0.20  # 20% platform fee


class Marketplace:
    """Agent marketplace — create, publish, discover, install, sell."""

    def __init__(self, db_fn, db_execute_fn, db_fetchall_fn, db_fetchone_fn, user_key_col: str = "user_api_key"):
        self._db_fn = db_fn
        self._db_execute = db_execute_fn
        self._db_fetchall = db_fetchall_fn
        self._db_fetchone = db_fetchone_fn
        self._user_key_col = user_key_col

    def init_tables(self, conn):
        """Create marketplace tables."""
        is_pg = hasattr(conn, 'autocommit')
        if is_pg:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS marketplace_agents (
                    id TEXT PRIMARY KEY,
                    creator_key TEXT NOT NULL,
                    creator_name TEXT DEFAULT 'anonymous',
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    long_description TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '[]',
                    system_prompt TEXT NOT NULL,
                    tools TEXT DEFAULT '[]',
                    model_preference TEXT DEFAULT '',
                    icon TEXT DEFAULT '🤖',
                    version TEXT DEFAULT '1.0.0',
                    price_usd REAL DEFAULT 0.0,
                    is_free INTEGER DEFAULT 1,
                    published INTEGER DEFAULT 0,
                    featured INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    total_runs INTEGER DEFAULT 0,
                    avg_rating REAL DEFAULT 0.0,
                    rating_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS marketplace_installs (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_slug TEXT NOT NULL,
                    installed_at TEXT NOT NULL,
                    last_used TEXT,
                    run_count INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS marketplace_reviews (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    user_api_key TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    review_text TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_packs (
                    id TEXT PRIMARY KEY,
                    creator_key TEXT NOT NULL,
                    creator_name TEXT DEFAULT 'anonymous',
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    agent_ids TEXT DEFAULT '[]',
                    workflow_configs TEXT DEFAULT '[]',
                    mcp_tool_configs TEXT DEFAULT '[]',
                    price_usd REAL DEFAULT 0.0,
                    is_free INTEGER DEFAULT 1,
                    published INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS creator_earnings (
                    id TEXT PRIMARY KEY,
                    creator_key TEXT NOT NULL,
                    agent_id TEXT,
                    pack_id TEXT,
                    buyer_key TEXT NOT NULL,
                    gross_amount REAL NOT NULL,
                    platform_fee REAL NOT NULL,
                    creator_amount REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mp_agents_creator ON marketplace_agents(creator_key);
                CREATE INDEX IF NOT EXISTS idx_mp_agents_category ON marketplace_agents(category);
                CREATE INDEX IF NOT EXISTS idx_mp_agents_published ON marketplace_agents(published);
                CREATE INDEX IF NOT EXISTS idx_mp_agents_slug ON marketplace_agents(slug);
                CREATE INDEX IF NOT EXISTS idx_mp_installs_user ON marketplace_installs(user_api_key);
                CREATE INDEX IF NOT EXISTS idx_mp_installs_agent ON marketplace_installs(agent_id);
                CREATE INDEX IF NOT EXISTS idx_mp_reviews_agent ON marketplace_reviews(agent_id);
                CREATE INDEX IF NOT EXISTS idx_mp_earnings_creator ON creator_earnings(creator_key);
            """)
            conn.commit()
        else:
            sql = """
                CREATE TABLE IF NOT EXISTS marketplace_agents (
                    id TEXT PRIMARY KEY,
                    creator_key TEXT NOT NULL,
                    creator_name TEXT DEFAULT 'anonymous',
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    long_description TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '[]',
                    system_prompt TEXT NOT NULL,
                    tools TEXT DEFAULT '[]',
                    model_preference TEXT DEFAULT '',
                    icon TEXT DEFAULT '🤖',
                    version TEXT DEFAULT '1.0.0',
                    price_usd REAL DEFAULT 0.0,
                    is_free INTEGER DEFAULT 1,
                    published INTEGER DEFAULT 0,
                    featured INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    total_runs INTEGER DEFAULT 0,
                    avg_rating REAL DEFAULT 0.0,
                    rating_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS marketplace_installs (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_slug TEXT NOT NULL,
                    installed_at TEXT NOT NULL,
                    last_used TEXT,
                    run_count INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS marketplace_reviews (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    user_api_key TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    review_text TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_packs (
                    id TEXT PRIMARY KEY,
                    creator_key TEXT NOT NULL,
                    creator_name TEXT DEFAULT 'anonymous',
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    agent_ids TEXT DEFAULT '[]',
                    workflow_configs TEXT DEFAULT '[]',
                    mcp_tool_configs TEXT DEFAULT '[]',
                    price_usd REAL DEFAULT 0.0,
                    is_free INTEGER DEFAULT 1,
                    published INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS creator_earnings (
                    id TEXT PRIMARY KEY,
                    creator_key TEXT NOT NULL,
                    agent_id TEXT,
                    pack_id TEXT,
                    buyer_key TEXT NOT NULL,
                    gross_amount REAL NOT NULL,
                    platform_fee REAL NOT NULL,
                    creator_amount REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mp_agents_category ON marketplace_agents(category);
                CREATE INDEX IF NOT EXISTS idx_mp_agents_published ON marketplace_agents(published);
            """
            conn.executescript(sql)
            conn.commit()

    # ─── CREATE & MANAGE AGENTS ──────────────────────────

    async def create_agent(
        self,
        creator_key: str,
        name: str,
        description: str,
        system_prompt: str,
        category: str = "general",
        tags: list = None,
        tools: list = None,
        model_preference: str = "",
        icon: str = "🤖",
        price_usd: float = 0.0,
        creator_name: str = "anonymous",
        long_description: str = "",
    ) -> dict:
        """Create a new custom agent."""
        agent_id = str(uuid.uuid4())
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")[:50]
        # Ensure unique slug
        slug = f"{slug}-{agent_id[:6]}"
        now = datetime.now(timezone.utc).isoformat()
        is_free = 1 if price_usd <= 0 else 0

        conn = self._db_fn()
        try:
            self._db_execute(conn,
                f"INSERT INTO marketplace_agents (id, creator_key, creator_name, slug, name, description, long_description, category, tags, system_prompt, tools, model_preference, icon, price_usd, is_free, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_id, creator_key, creator_name, slug, name, description, long_description,
                 category, json.dumps(tags or []), system_prompt, json.dumps(tools or []),
                 model_preference, icon, price_usd, is_free, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        return {"agent_id": agent_id, "slug": slug, "name": name, "status": "draft"}

    async def publish_agent(self, agent_id: str, creator_key: str) -> dict:
        """Publish an agent to the marketplace."""
        conn = self._db_fn()
        try:
            self._db_execute(conn,
                "UPDATE marketplace_agents SET published = 1, updated_at = ? WHERE id = ? AND creator_key = ?",
                (datetime.now(timezone.utc).isoformat(), agent_id, creator_key),
            )
            conn.commit()
        finally:
            conn.close()
        return {"agent_id": agent_id, "status": "published"}

    async def unpublish_agent(self, agent_id: str, creator_key: str) -> dict:
        conn = self._db_fn()
        try:
            self._db_execute(conn,
                "UPDATE marketplace_agents SET published = 0, updated_at = ? WHERE id = ? AND creator_key = ?",
                (datetime.now(timezone.utc).isoformat(), agent_id, creator_key),
            )
            conn.commit()
        finally:
            conn.close()
        return {"agent_id": agent_id, "status": "unpublished"}

    async def update_agent(self, agent_id: str, creator_key: str, updates: dict) -> dict:
        """Update agent fields."""
        allowed = {"name", "description", "long_description", "system_prompt", "category",
                    "tags", "tools", "model_preference", "icon", "price_usd", "version"}
        conn = self._db_fn()
        try:
            for field, value in updates.items():
                if field not in allowed:
                    continue
                if field in ("tags", "tools"):
                    value = json.dumps(value)
                if field == "price_usd":
                    self._db_execute(conn,
                        f"UPDATE marketplace_agents SET {field} = ?, is_free = ?, updated_at = ? WHERE id = ? AND creator_key = ?",
                        (value, 1 if value <= 0 else 0, datetime.now(timezone.utc).isoformat(), agent_id, creator_key),
                    )
                else:
                    self._db_execute(conn,
                        f"UPDATE marketplace_agents SET {field} = ?, updated_at = ? WHERE id = ? AND creator_key = ?",
                        (value, datetime.now(timezone.utc).isoformat(), agent_id, creator_key),
                    )
            conn.commit()
        finally:
            conn.close()
        return {"agent_id": agent_id, "status": "updated"}

    async def get_my_agents(self, creator_key: str) -> list:
        conn = self._db_fn()
        try:
            rows = self._db_fetchall(conn,
                "SELECT id, slug, name, description, icon, category, price_usd, published, install_count, total_runs, avg_rating, rating_count, version, created_at FROM marketplace_agents WHERE creator_key = ? ORDER BY created_at DESC",
                (creator_key,),
            )
        finally:
            conn.close()
        return [
            {"agent_id": r[0], "slug": r[1], "name": r[2], "description": r[3], "icon": r[4],
             "category": r[5], "price_usd": r[6], "published": bool(r[7]), "install_count": r[8],
             "total_runs": r[9], "avg_rating": r[10], "rating_count": r[11], "version": r[12], "created_at": r[13]}
            for r in rows
        ]

    # ─── BROWSE & SEARCH ─────────────────────────────────

    async def browse(self, category: str = None, search: str = None, sort: str = "popular", limit: int = 20, offset: int = 0) -> list:
        """Browse published marketplace agents."""
        conn = self._db_fn()
        try:
            base = "SELECT id, slug, name, description, icon, category, tags, price_usd, is_free, creator_name, install_count, total_runs, avg_rating, rating_count, version FROM marketplace_agents WHERE published = 1"
            params = []

            if category:
                base += " AND category = ?"
                params.append(category)
            if search:
                base += " AND (name LIKE ? OR description LIKE ? OR tags LIKE ?)"
                s = f"%{search}%"
                params.extend([s, s, s])

            if sort == "popular":
                base += " ORDER BY install_count DESC"
            elif sort == "newest":
                base += " ORDER BY created_at DESC"
            elif sort == "rating":
                base += " ORDER BY avg_rating DESC"
            elif sort == "free":
                base += " AND is_free = 1 ORDER BY install_count DESC"

            base += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = self._db_fetchall(conn, base, tuple(params))
        finally:
            conn.close()

        return [
            {"agent_id": r[0], "slug": r[1], "name": r[2], "description": r[3], "icon": r[4],
             "category": r[5], "tags": json.loads(r[6]) if r[6] else [], "price_usd": r[7],
             "is_free": bool(r[8]), "creator": r[9], "install_count": r[10], "total_runs": r[11],
             "avg_rating": r[12], "rating_count": r[13], "version": r[14]}
            for r in rows
        ]

    async def get_agent_detail(self, slug_or_id: str) -> Optional[dict]:
        """Get full agent details."""
        conn = self._db_fn()
        try:
            row = self._db_fetchone(conn,
                "SELECT id, slug, name, description, long_description, icon, category, tags, system_prompt, tools, model_preference, price_usd, is_free, creator_name, creator_key, install_count, total_runs, avg_rating, rating_count, version, published, created_at, updated_at FROM marketplace_agents WHERE (slug = ? OR id = ?)",
                (slug_or_id, slug_or_id),
            )
        finally:
            conn.close()

        if not row:
            return None
        return {
            "agent_id": row[0], "slug": row[1], "name": row[2], "description": row[3],
            "long_description": row[4], "icon": row[5], "category": row[6],
            "tags": json.loads(row[7]) if row[7] else [], "system_prompt": row[8],
            "tools": json.loads(row[9]) if row[9] else [], "model_preference": row[10],
            "price_usd": row[11], "is_free": bool(row[12]), "creator": row[13],
            "creator_key": row[14], "install_count": row[15], "total_runs": row[16],
            "avg_rating": row[17], "rating_count": row[18], "version": row[19],
            "published": bool(row[20]), "created_at": row[21], "updated_at": row[22],
        }

    # ─── INSTALL & USE ───────────────────────────────────

    async def install_agent(self, user_api_key: str, agent_id: str) -> dict:
        """Install a marketplace agent for the user."""
        # Get agent details
        agent = await self.get_agent_detail(agent_id)
        if not agent:
            return {"error": "Agent not found"}
        if not agent["published"]:
            return {"error": "Agent not published"}

        # Check if already installed
        conn = self._db_fn()
        try:
            existing = self._db_fetchone(conn,
                "SELECT id FROM marketplace_installs WHERE user_api_key = ? AND agent_id = ? AND enabled = 1",
                (user_api_key, agent_id),
            )
            if existing:
                return {"error": "Already installed"}

            # Record install
            install_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            self._db_execute(conn,
                "INSERT INTO marketplace_installs (id, user_api_key, agent_id, agent_slug, installed_at) VALUES (?, ?, ?, ?, ?)",
                (install_id, user_api_key, agent_id, agent["slug"], now),
            )
            # Increment install count
            self._db_execute(conn,
                "UPDATE marketplace_agents SET install_count = install_count + 1 WHERE id = ?",
                (agent_id,),
            )

            # Handle payment if not free
            if not agent["is_free"] and agent["price_usd"] > 0:
                earning_id = str(uuid.uuid4())
                gross = agent["price_usd"]
                fee = round(gross * PLATFORM_FEE, 2)
                creator_amt = round(gross - fee, 2)
                self._db_execute(conn,
                    "INSERT INTO creator_earnings (id, creator_key, agent_id, buyer_key, gross_amount, platform_fee, creator_amount, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (earning_id, agent["creator_key"], agent_id, user_api_key, gross, fee, creator_amt, now),
                )

            conn.commit()
        finally:
            conn.close()

        return {"install_id": install_id, "agent": agent["name"], "slug": agent["slug"], "status": "installed"}

    async def uninstall_agent(self, user_api_key: str, agent_id: str) -> dict:
        conn = self._db_fn()
        try:
            self._db_execute(conn,
                "UPDATE marketplace_installs SET enabled = 0 WHERE user_api_key = ? AND agent_id = ?",
                (user_api_key, agent_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "uninstalled"}

    async def get_installed(self, user_api_key: str) -> list:
        """Get user's installed marketplace agents."""
        conn = self._db_fn()
        try:
            rows = self._db_fetchall(conn,
                """SELECT mi.agent_id, mi.agent_slug, ma.name, ma.description, ma.icon, ma.category,
                          ma.system_prompt, ma.tools, ma.model_preference, mi.run_count, mi.installed_at
                   FROM marketplace_installs mi
                   JOIN marketplace_agents ma ON mi.agent_id = ma.id
                   WHERE mi.user_api_key = ? AND mi.enabled = 1
                   ORDER BY mi.installed_at DESC""",
                (user_api_key,),
            )
        finally:
            conn.close()

        return [
            {"agent_id": r[0], "slug": r[1], "name": r[2], "description": r[3], "icon": r[4],
             "category": r[5], "system_prompt": r[6], "tools": json.loads(r[7]) if r[7] else [],
             "model_preference": r[8], "run_count": r[9], "installed_at": r[10]}
            for r in rows
        ]

    async def record_run(self, agent_id: str, user_api_key: str):
        """Record that a marketplace agent was used."""
        conn = self._db_fn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            self._db_execute(conn,
                "UPDATE marketplace_installs SET run_count = run_count + 1, last_used = ? WHERE agent_id = ? AND user_api_key = ?",
                (now, agent_id, user_api_key),
            )
            self._db_execute(conn,
                "UPDATE marketplace_agents SET total_runs = total_runs + 1 WHERE id = ?",
                (agent_id,),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    # ─── REVIEWS ─────────────────────────────────────────

    async def add_review(self, agent_id: str, user_api_key: str, rating: int, review_text: str = "") -> dict:
        """Add or update a review."""
        if rating < 1 or rating > 5:
            return {"error": "Rating must be 1-5"}

        conn = self._db_fn()
        try:
            # Check if already reviewed
            existing = self._db_fetchone(conn,
                "SELECT id FROM marketplace_reviews WHERE agent_id = ? AND user_api_key = ?",
                (agent_id, user_api_key),
            )
            now = datetime.now(timezone.utc).isoformat()

            if existing:
                self._db_execute(conn,
                    "UPDATE marketplace_reviews SET rating = ?, review_text = ?, created_at = ? WHERE agent_id = ? AND user_api_key = ?",
                    (rating, review_text, now, agent_id, user_api_key),
                )
            else:
                review_id = str(uuid.uuid4())
                self._db_execute(conn,
                    "INSERT INTO marketplace_reviews (id, agent_id, user_api_key, rating, review_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (review_id, agent_id, user_api_key, rating, review_text, now),
                )

            # Recalculate average
            avg_row = self._db_fetchone(conn,
                "SELECT AVG(rating), COUNT(*) FROM marketplace_reviews WHERE agent_id = ?",
                (agent_id,),
            )
            if avg_row:
                self._db_execute(conn,
                    "UPDATE marketplace_agents SET avg_rating = ?, rating_count = ? WHERE id = ?",
                    (round(avg_row[0] or 0, 2), avg_row[1] or 0, agent_id),
                )
            conn.commit()
        finally:
            conn.close()

        return {"status": "reviewed", "rating": rating}

    async def get_reviews(self, agent_id: str, limit: int = 20) -> list:
        conn = self._db_fn()
        try:
            rows = self._db_fetchall(conn,
                "SELECT rating, review_text, created_at FROM marketplace_reviews WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            )
        finally:
            conn.close()
        return [{"rating": r[0], "review": r[1], "created_at": r[2]} for r in rows]

    # ─── EARNINGS ────────────────────────────────────────

    async def get_earnings(self, creator_key: str) -> dict:
        """Get creator earnings summary."""
        conn = self._db_fn()
        try:
            totals = self._db_fetchone(conn,
                "SELECT COALESCE(SUM(gross_amount), 0), COALESCE(SUM(creator_amount), 0), COUNT(*) FROM creator_earnings WHERE creator_key = ?",
                (creator_key,),
            )
            recent = self._db_fetchall(conn,
                "SELECT agent_id, gross_amount, creator_amount, created_at FROM creator_earnings WHERE creator_key = ? ORDER BY created_at DESC LIMIT 20",
                (creator_key,),
            )
        finally:
            conn.close()

        return {
            "total_gross": totals[0] if totals else 0,
            "total_earned": totals[1] if totals else 0,
            "total_sales": totals[2] if totals else 0,
            "platform_fee_rate": PLATFORM_FEE,
            "recent_sales": [
                {"agent_id": r[0], "gross": r[1], "earned": r[2], "date": r[3]}
                for r in recent
            ],
        }

    # ─── SKILL PACKS ─────────────────────────────────────

    async def create_skill_pack(
        self,
        creator_key: str,
        name: str,
        description: str,
        agent_ids: list = None,
        workflow_configs: list = None,
        mcp_tool_configs: list = None,
        price_usd: float = 0.0,
        creator_name: str = "anonymous",
    ) -> dict:
        """Create a skill pack (bundle of agents + workflows + tools)."""
        pack_id = str(uuid.uuid4())
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")[:50]
        slug = f"{slug}-{pack_id[:6]}"
        now = datetime.now(timezone.utc).isoformat()

        conn = self._db_fn()
        try:
            self._db_execute(conn,
                "INSERT INTO skill_packs (id, creator_key, creator_name, slug, name, description, agent_ids, workflow_configs, mcp_tool_configs, price_usd, is_free, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pack_id, creator_key, creator_name, slug, name, description,
                 json.dumps(agent_ids or []), json.dumps(workflow_configs or []),
                 json.dumps(mcp_tool_configs or []), price_usd, 1 if price_usd <= 0 else 0, now),
            )
            conn.commit()
        finally:
            conn.close()

        return {"pack_id": pack_id, "slug": slug, "name": name}

    async def get_marketplace_stats(self) -> dict:
        """Get overall marketplace stats."""
        conn = self._db_fn()
        try:
            agents_count = self._db_fetchone(conn, "SELECT COUNT(*) FROM marketplace_agents WHERE published = 1", ())
            installs_count = self._db_fetchone(conn, "SELECT COUNT(*) FROM marketplace_installs WHERE enabled = 1", ())
            creators_count = self._db_fetchone(conn, "SELECT COUNT(DISTINCT creator_key) FROM marketplace_agents WHERE published = 1", ())
            total_runs = self._db_fetchone(conn, "SELECT COALESCE(SUM(total_runs), 0) FROM marketplace_agents", ())
        finally:
            conn.close()

        return {
            "published_agents": agents_count[0] if agents_count else 0,
            "total_installs": installs_count[0] if installs_count else 0,
            "active_creators": creators_count[0] if creators_count else 0,
            "total_agent_runs": total_runs[0] if total_runs else 0,
        }


# ─── FEATURED / STARTER AGENTS ──────────────────────────

STARTER_AGENTS = [
    {
        "name": "Alpha Hunter",
        "description": "Scans crypto markets for undervalued tokens with strong fundamentals. Combines on-chain data, social sentiment, and technical analysis.",
        "category": "Crypto & DeFi",
        "icon": "🎯",
        "system_prompt": "You are Alpha Hunter, an expert crypto analyst specializing in finding undervalued tokens. Analyze on-chain metrics (TVL, active addresses, transaction volume), social sentiment (Twitter/Discord buzz, developer activity), and technical indicators (RSI, MACD, support/resistance). Provide a clear bull/bear thesis with specific entry/exit points and risk assessment. Always include a confidence score 1-10.",
        "tags": ["crypto", "alpha", "trading", "analysis"],
        "tools": ["web_search", "crypto_prices", "fetch_url", "run_code"],
    },
    {
        "name": "Content Machine",
        "description": "Creates viral social media content. Writes threads, hooks, carousels, and repurposes content across platforms.",
        "category": "Writing & Content",
        "icon": "🧵",
        "system_prompt": "You are Content Machine, an expert at creating viral social media content. You write punchy Twitter/X threads with strong hooks, LinkedIn posts optimized for engagement, and short-form content ideas. Every piece follows the hook → story → insight → CTA framework. You understand algorithm preferences for each platform. Output specific, ready-to-post content — not generic advice.",
        "tags": ["content", "social", "viral", "threads", "marketing"],
        "tools": ["web_search", "fetch_url"],
    },
    {
        "name": "Deal Analyzer",
        "description": "Evaluates startup deals, investment opportunities, and business proposals with financial modeling.",
        "category": "Business & Strategy",
        "icon": "💰",
        "system_prompt": "You are Deal Analyzer, a seasoned VC analyst. When given a startup, deal, or investment opportunity, you evaluate: market size (TAM/SAM/SOM), competitive landscape, team assessment, business model viability, unit economics, and comparable valuations. Build financial projections and identify key risks. Output a structured investment memo with a clear PASS/CONSIDER/INVEST recommendation and conviction level.",
        "tags": ["investing", "startups", "finance", "analysis"],
        "tools": ["web_search", "fetch_url", "run_code"],
    },
    {
        "name": "Security Auditor",
        "description": "Audits code, smart contracts, and systems for vulnerabilities. Provides severity ratings and remediation steps.",
        "category": "Coding & Dev",
        "icon": "🔒",
        "system_prompt": "You are Security Auditor, a cybersecurity expert. Audit code, architectures, and smart contracts for vulnerabilities. Classify findings by severity (Critical/High/Medium/Low/Info), provide proof-of-concept attack scenarios, and give specific remediation steps. Check for OWASP Top 10, common smart contract issues (reentrancy, front-running, access control), and infrastructure misconfigurations. Output a structured audit report.",
        "tags": ["security", "audit", "code", "vulnerabilities"],
        "tools": ["web_search", "fetch_url", "run_code"],
    },
    {
        "name": "Growth Hacker",
        "description": "Designs growth experiments, analyzes funnels, and creates acquisition strategies for products and startups.",
        "category": "Business & Strategy",
        "icon": "📈",
        "system_prompt": "You are Growth Hacker, an expert at rapid experimentation for user acquisition and retention. When given a product or business, you design specific, actionable growth experiments with hypotheses, metrics, and expected outcomes. Analyze conversion funnels, identify bottlenecks, and suggest A/B tests. Prioritize using ICE (Impact/Confidence/Ease) scoring. Focus on channels: SEO, paid ads, viral loops, partnerships, content, community, product-led growth.",
        "tags": ["growth", "marketing", "startup", "acquisition"],
        "tools": ["web_search", "fetch_url", "run_code"],
    },
]
