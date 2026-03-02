"""
APEX SWARM - MCP Tool Registry & Rate Limiter
===============================================
Dynamic tool registration so users can bring their own APIs.

Features:
  1. Tool Registry — Register external APIs as agent tools
  2. MCP-style Interface — Normalize any API into a common tool schema
  3. Tool Execution — Call registered tools during agent execution
  4. Rate Limiter — Per-user, per-tier request throttling
  5. Tier Enforcement — Limits on agents, daemons, schedules per tier

File: mcp_registry.py
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("apex-swarm")


# ─── RATE LIMITER ─────────────────────────────────────────

class RateLimiter:
    """Token-bucket rate limiter per user."""

    def __init__(self):
        self._buckets: dict[str, dict] = {}
        self._daily_counts: dict[str, dict] = {}

    def _get_bucket(self, user_key: str, tier: str) -> dict:
        """Get or create a rate limit bucket for a user."""
        if user_key not in self._buckets:
            self._buckets[user_key] = {
                "tokens": self._max_rpm(tier),
                "last_refill": time.time(),
                "tier": tier,
            }
        return self._buckets[user_key]

    def _max_rpm(self, tier: str) -> int:
        """Max requests per minute by tier."""
        return {
            "free": 3,
            "starter": 10,
            "pro": 30,
            "enterprise": 100,
            "admin": 9999,
        }.get(tier, 3)

    def _max_daily(self, tier: str) -> int:
        """Max requests per day by tier."""
        return {
            "free": 10,
            "starter": 50,
            "pro": 200,
            "enterprise": 2000,
            "admin": 999999,
        }.get(tier, 10)

    def check(self, user_key: str, tier: str = "free") -> dict:
        """Check if user can make a request. Returns {allowed, remaining, reset_in}."""
        now = time.time()

        # Per-minute bucket
        bucket = self._get_bucket(user_key, tier)
        elapsed = now - bucket["last_refill"]
        max_rpm = self._max_rpm(tier)

        # Refill tokens based on elapsed time
        refill = elapsed * (max_rpm / 60.0)
        bucket["tokens"] = min(max_rpm, bucket["tokens"] + refill)
        bucket["last_refill"] = now
        bucket["tier"] = tier

        # Daily count
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if user_key not in self._daily_counts:
            self._daily_counts[user_key] = {"date": today, "count": 0}
        if self._daily_counts[user_key]["date"] != today:
            self._daily_counts[user_key] = {"date": today, "count": 0}

        daily = self._daily_counts[user_key]
        max_daily = self._max_daily(tier)

        if bucket["tokens"] < 1:
            return {
                "allowed": False,
                "reason": "rate_limit",
                "message": f"Rate limit exceeded. Max {max_rpm} requests/minute for {tier} tier.",
                "remaining_rpm": 0,
                "remaining_daily": max_daily - daily["count"],
                "reset_in_seconds": int((1 - bucket["tokens"]) / (max_rpm / 60.0)) + 1,
            }

        if daily["count"] >= max_daily:
            return {
                "allowed": False,
                "reason": "daily_limit",
                "message": f"Daily limit exceeded. Max {max_daily} requests/day for {tier} tier.",
                "remaining_rpm": int(bucket["tokens"]),
                "remaining_daily": 0,
                "reset_in_seconds": None,
            }

        return {
            "allowed": True,
            "remaining_rpm": int(bucket["tokens"]),
            "remaining_daily": max_daily - daily["count"],
        }

    def consume(self, user_key: str, tier: str = "free"):
        """Consume a rate limit token after allowing a request."""
        bucket = self._get_bucket(user_key, tier)
        bucket["tokens"] = max(0, bucket["tokens"] - 1)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if user_key not in self._daily_counts:
            self._daily_counts[user_key] = {"date": today, "count": 0}
        if self._daily_counts[user_key]["date"] != today:
            self._daily_counts[user_key] = {"date": today, "count": 0}
        self._daily_counts[user_key]["count"] += 1

    def get_usage(self, user_key: str, tier: str = "free") -> dict:
        """Get current usage stats for a user."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self._daily_counts.get(user_key, {"date": today, "count": 0})
        if daily["date"] != today:
            daily = {"date": today, "count": 0}

        max_rpm = self._max_rpm(tier)
        max_daily = self._max_daily(tier)
        bucket = self._get_bucket(user_key, tier)

        return {
            "tier": tier,
            "requests_today": daily["count"],
            "max_daily": max_daily,
            "remaining_daily": max_daily - daily["count"],
            "remaining_rpm": int(bucket["tokens"]),
            "max_rpm": max_rpm,
        }


# ─── TIER ENFORCEMENT ─────────────────────────────────────

class TierEnforcer:
    """Enforce tier limits on daemons, schedules, etc."""

    def __init__(self, db_fn, db_fetchone_fn, user_key_col: str = "user_api_key"):
        self._db_fn = db_fn
        self._db_fetchone = db_fetchone_fn
        self._user_key_col = user_key_col

    # Tier limits
    LIMITS = {
        "free": {"max_daemons": 0, "max_schedules": 0, "tools": False, "memory": False, "mcp_tools": 0},
        "starter": {"max_daemons": 1, "max_schedules": 3, "tools": True, "memory": True, "mcp_tools": 3},
        "pro": {"max_daemons": 5, "max_schedules": 10, "tools": True, "memory": True, "mcp_tools": 10},
        "enterprise": {"max_daemons": 50, "max_schedules": 100, "tools": True, "memory": True, "mcp_tools": 50},
        "admin": {"max_daemons": 999, "max_schedules": 999, "tools": True, "memory": True, "mcp_tools": 999},
    }

    def get_limits(self, tier: str) -> dict:
        return self.LIMITS.get(tier, self.LIMITS["free"])

    def check_daemon_limit(self, user_api_key: str, tier: str) -> dict:
        """Check if user can start another daemon."""
        limits = self.get_limits(tier)
        max_daemons = limits["max_daemons"]

        conn = self._db_fn()
        try:
            row = self._db_fetchone(conn,
                f"SELECT COUNT(*) FROM daemon_configs WHERE {self._user_key_col} = ? AND enabled = 1",
                (user_api_key,),
            )
            current = row[0] if row else 0
        finally:
            conn.close()

        if current >= max_daemons:
            return {"allowed": False, "message": f"Daemon limit reached ({current}/{max_daemons}) for {tier} tier. Upgrade for more."}
        return {"allowed": True, "current": current, "max": max_daemons}

    def check_schedule_limit(self, user_api_key: str, tier: str) -> dict:
        """Check if user can create another schedule."""
        limits = self.get_limits(tier)
        max_schedules = limits["max_schedules"]

        conn = self._db_fn()
        try:
            row = self._db_fetchone(conn,
                f"SELECT COUNT(*) FROM schedules WHERE {self._user_key_col} = ? AND enabled = 1",
                (user_api_key,),
            )
            current = row[0] if row else 0
        finally:
            conn.close()

        if current >= max_schedules:
            return {"allowed": False, "message": f"Schedule limit reached ({current}/{max_schedules}) for {tier} tier."}
        return {"allowed": True, "current": current, "max": max_schedules}

    def check_mcp_limit(self, user_api_key: str, tier: str) -> dict:
        """Check if user can register another MCP tool."""
        limits = self.get_limits(tier)
        max_tools = limits["mcp_tools"]

        conn = self._db_fn()
        try:
            row = self._db_fetchone(conn,
                f"SELECT COUNT(*) FROM mcp_tools WHERE {self._user_key_col} = ? AND enabled = 1",
                (user_api_key,),
            )
            current = row[0] if row else 0
        except Exception:
            current = 0
        finally:
            conn.close()

        if current >= max_tools:
            return {"allowed": False, "message": f"MCP tool limit reached ({current}/{max_tools}) for {tier} tier."}
        return {"allowed": True, "current": current, "max": max_tools}


# ─── MCP TOOL REGISTRY ───────────────────────────────────

class MCPRegistry:
    """Dynamic tool registry — users register external APIs as agent tools."""

    def __init__(self, db_fn, db_execute_fn, db_fetchall_fn, db_fetchone_fn, user_key_col: str = "user_api_key"):
        self._db_fn = db_fn
        self._db_execute = db_execute_fn
        self._db_fetchall = db_fetchall_fn
        self._db_fetchone = db_fetchone_fn
        self._user_key_col = user_key_col

    def init_tables(self, conn):
        """Create MCP tables."""
        is_pg = hasattr(conn, 'autocommit')
        if is_pg:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mcp_tools (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    endpoint_url TEXT NOT NULL,
                    method TEXT DEFAULT 'GET',
                    headers TEXT DEFAULT '{}',
                    body_template TEXT DEFAULT '',
                    query_params TEXT DEFAULT '{}',
                    auth_type TEXT DEFAULT 'none',
                    auth_value TEXT DEFAULT '',
                    input_schema TEXT DEFAULT '{}',
                    output_mapping TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    enabled INTEGER DEFAULT 1,
                    call_count INTEGER DEFAULT 0,
                    last_called TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mcp_user ON mcp_tools(user_api_key);
                CREATE INDEX IF NOT EXISTS idx_mcp_category ON mcp_tools(category);
            """)
            conn.commit()
        else:
            sql = """
                CREATE TABLE IF NOT EXISTS mcp_tools (
                    id TEXT PRIMARY KEY,
                    """ + self._user_key_col + """ TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    endpoint_url TEXT NOT NULL,
                    method TEXT DEFAULT 'GET',
                    headers TEXT DEFAULT '{}',
                    body_template TEXT DEFAULT '',
                    query_params TEXT DEFAULT '{}',
                    auth_type TEXT DEFAULT 'none',
                    auth_value TEXT DEFAULT '',
                    input_schema TEXT DEFAULT '{}',
                    output_mapping TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    enabled INTEGER DEFAULT 1,
                    call_count INTEGER DEFAULT 0,
                    last_called TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mcp_category ON mcp_tools(category);
            """
            conn.executescript(sql)
            try:
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_mcp_user ON mcp_tools({self._user_key_col})")
            except Exception:
                pass
            conn.commit()

    async def register_tool(
        self,
        user_api_key: str,
        name: str,
        description: str,
        endpoint_url: str,
        method: str = "GET",
        headers: dict = None,
        body_template: str = "",
        query_params: dict = None,
        auth_type: str = "none",
        auth_value: str = "",
        input_schema: dict = None,
        output_mapping: str = "",
        category: str = "general",
    ) -> dict:
        """Register a new external API as an agent tool."""
        tool_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = self._db_fn()
        try:
            self._db_execute(conn,
                f"INSERT INTO mcp_tools (id, {self._user_key_col}, name, description, endpoint_url, method, headers, body_template, query_params, auth_type, auth_value, input_schema, output_mapping, category, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tool_id, user_api_key, name, description, endpoint_url, method.upper(),
                 json.dumps(headers or {}), body_template, json.dumps(query_params or {}),
                 auth_type, auth_value, json.dumps(input_schema or {}), output_mapping, category, now),
            )
            conn.commit()
        finally:
            conn.close()

        return {"tool_id": tool_id, "name": name, "status": "registered"}

    async def get_tools(self, user_api_key: str, category: str = None) -> list[dict]:
        """Get registered tools for a user."""
        conn = self._db_fn()
        try:
            if category:
                rows = self._db_fetchall(conn,
                    f"SELECT id, name, description, endpoint_url, method, category, call_count FROM mcp_tools WHERE {self._user_key_col} = ? AND category = ? AND enabled = 1",
                    (user_api_key, category),
                )
            else:
                rows = self._db_fetchall(conn,
                    f"SELECT id, name, description, endpoint_url, method, category, call_count FROM mcp_tools WHERE {self._user_key_col} = ? AND enabled = 1",
                    (user_api_key,),
                )
        finally:
            conn.close()

        return [
            {"tool_id": r[0], "name": r[1], "description": r[2], "endpoint_url": r[3],
             "method": r[4], "category": r[5], "call_count": r[6]}
            for r in rows
        ]

    async def execute_tool(self, tool_id: str, user_api_key: str, input_data: dict = None) -> dict:
        """Execute a registered tool by calling its endpoint."""
        conn = self._db_fn()
        try:
            row = self._db_fetchone(conn,
                f"SELECT name, endpoint_url, method, headers, body_template, query_params, auth_type, auth_value, output_mapping FROM mcp_tools WHERE id = ? AND {self._user_key_col} = ? AND enabled = 1",
                (tool_id, user_api_key),
            )
        finally:
            conn.close()

        if not row:
            return {"error": "Tool not found or disabled"}

        name, url, method, headers_json, body_template, query_json, auth_type, auth_value, output_mapping = row

        try:
            headers = json.loads(headers_json) if headers_json else {}
            query_params = json.loads(query_json) if query_json else {}
        except Exception:
            headers = {}
            query_params = {}

        # Apply auth
        if auth_type == "bearer" and auth_value:
            headers["Authorization"] = f"Bearer {auth_value}"
        elif auth_type == "api_key" and auth_value:
            headers["X-Api-Key"] = auth_value

        # Substitute input data into URL, body, params
        input_data = input_data or {}
        for key, val in input_data.items():
            url = url.replace(f"{{{key}}}", str(val))
            body_template = body_template.replace(f"{{{key}}}", str(val)) if body_template else ""
            for pk, pv in query_params.items():
                if isinstance(pv, str):
                    query_params[pk] = pv.replace(f"{{{key}}}", str(val))

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=query_params)
                elif method == "POST":
                    body = json.loads(body_template) if body_template else input_data
                    resp = await client.post(url, headers=headers, json=body, params=query_params)
                elif method == "PUT":
                    body = json.loads(body_template) if body_template else input_data
                    resp = await client.put(url, headers=headers, json=body)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers)
                else:
                    return {"error": f"Unsupported method: {method}"}

            # Update call count
            conn = self._db_fn()
            try:
                now = datetime.now(timezone.utc).isoformat()
                self._db_execute(conn,
                    "UPDATE mcp_tools SET call_count = call_count + 1, last_called = ? WHERE id = ?",
                    (now, tool_id),
                )
                conn.commit()
            finally:
                conn.close()

            # Parse response
            try:
                result_data = resp.json()
            except Exception:
                result_data = {"raw": resp.text[:2000]}

            return {
                "tool": name,
                "status_code": resp.status_code,
                "result": result_data,
            }

        except Exception as e:
            return {"tool": name, "error": str(e)}

    async def delete_tool(self, tool_id: str, user_api_key: str) -> bool:
        """Disable a registered tool."""
        conn = self._db_fn()
        try:
            self._db_execute(conn,
                f"UPDATE mcp_tools SET enabled = 0 WHERE id = ? AND {self._user_key_col} = ?",
                (tool_id, user_api_key),
            )
            conn.commit()
        finally:
            conn.close()
        return True

    def get_tool_definitions_for_claude(self, tools: list[dict]) -> str:
        """Format registered tools as context for Claude to know what's available."""
        if not tools:
            return ""
        lines = ["\n\n## Custom Tools Available (registered by user):\n"]
        for t in tools:
            lines.append(f"- **{t['name']}**: {t['description']} (calls: {t['method']} {t['endpoint_url'][:50]})")
        lines.append("\nYou can request to use any of these tools by saying: USE_TOOL: <tool_name> with <input>")
        return "\n".join(lines)


# ─── PRESET MCP TEMPLATES ────────────────────────────────

MCP_TEMPLATES = {
    "coingecko": {
        "name": "CoinGecko Prices",
        "description": "Get real-time cryptocurrency prices from CoinGecko",
        "endpoint_url": "https://api.coingecko.com/api/v3/simple/price?ids={coin_ids}&vs_currencies=usd&include_24hr_change=true",
        "method": "GET",
        "category": "crypto",
        "input_schema": {"coin_ids": "bitcoin,ethereum,solana"},
    },
    "newsapi": {
        "name": "News API Search",
        "description": "Search recent news articles by keyword",
        "endpoint_url": "https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize=5",
        "method": "GET",
        "auth_type": "api_key",
        "category": "research",
        "input_schema": {"query": "search term"},
    },
    "github-trending": {
        "name": "GitHub Trending",
        "description": "Get trending GitHub repositories",
        "endpoint_url": "https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page=5",
        "method": "GET",
        "category": "code",
        "input_schema": {"query": "topic or language"},
    },
    "webhook": {
        "name": "Custom Webhook",
        "description": "Send data to a custom webhook URL",
        "endpoint_url": "",
        "method": "POST",
        "category": "general",
        "input_schema": {"payload": "any JSON data"},
    },
}


# ─── GLOBAL INSTANCES ────────────────────────────────────

rate_limiter = RateLimiter()
