"""
agent_identity.py — APEX SWARM Agent Identity Containers
Each agent gets an isolated identity: email alias, Stripe account, API credentials.
Agents never touch the owner's personal accounts.
Inspired by the Felix model: separate container = maximum autonomy + zero personal risk.
"""

import json
import uuid
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── IDENTITY CONTAINER ───────────────────────────────────

class AgentIdentity:
    """
    Represents a fully isolated agent identity.
    
    Each agent has:
    - SOUL: who it is (name, mission, personality)
    - CREDENTIALS: what it can access (email alias, API keys, Stripe)
    - PERMISSIONS: what it's allowed to do (scopes)
    - WALLET: its own budget and spending limits
    """

    def __init__(self, data: dict):
        self.container_id = data["container_id"]
        self.daemon_id = data.get("daemon_id")
        self.owner_api_key = data["owner_api_key"]
        self.agent_name = data["agent_name"]
        self.agent_type = data["agent_type"]
        self.mission = data.get("mission", "")

        # Credentials (what the agent can access)
        self.email_alias = data.get("email_alias", "")
        self.credentials = json.loads(data.get("credentials", "{}"))
        
        # Permissions (what the agent is allowed to do)
        self.permissions = json.loads(data.get("permissions", "[]"))
        
        # Wallet (agent's own budget)
        self.wallet_budget_usd = data.get("wallet_budget_usd", 0.0)
        self.wallet_spent_usd = data.get("wallet_spent_usd", 0.0)
        self.spending_limit_per_action = data.get("spending_limit_per_action", 10.0)
        
        # State
        self.active = data.get("active", True)
        self.created_at = data.get("created_at", "")
        self.last_used_at = data.get("last_used_at", "")

    @property
    def wallet_remaining(self) -> float:
        return max(0.0, self.wallet_budget_usd - self.wallet_spent_usd)

    @property
    def can_spend(self) -> bool:
        return self.wallet_remaining >= self.spending_limit_per_action

    def has_permission(self, scope: str) -> bool:
        return scope in self.permissions or "admin" in self.permissions

    def to_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "daemon_id": self.daemon_id,
            "owner_api_key": self.owner_api_key,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "mission": self.mission,
            "email_alias": self.email_alias,
            "credentials": json.dumps(self.credentials),
            "permissions": json.dumps(self.permissions),
            "wallet_budget_usd": self.wallet_budget_usd,
            "wallet_spent_usd": self.wallet_spent_usd,
            "spending_limit_per_action": self.spending_limit_per_action,
            "active": self.active,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }

    def to_prompt_context(self) -> str:
        """Inject identity into agent system prompt."""
        cred_summary = []
        for service, cred in self.credentials.items():
            if isinstance(cred, dict):
                cred_summary.append(f"{service}: configured")
            else:
                cred_summary.append(f"{service}: available")

        return f"""
--- AGENT IDENTITY CONTAINER ---
NAME: {self.agent_name}
MISSION: {self.mission}
EMAIL: {self.email_alias or 'not configured'}
CREDENTIALS: {', '.join(cred_summary) or 'none configured'}
PERMISSIONS: {', '.join(self.permissions) or 'read-only'}
WALLET: ${self.wallet_remaining:.2f} remaining (limit ${self.spending_limit_per_action:.2f}/action)
HARD RULES:
- Never use the owner's personal credentials
- Never spend more than ${self.spending_limit_per_action:.2f} per action without approval
- Never share credentials with other agents
- Always operate within assigned permissions: {', '.join(self.permissions) or 'none'}
--- END IDENTITY ---
"""


# ─── IDENTITY MANAGER ────────────────────────────────────

class AgentIdentityManager:
    """Manages creation, retrieval, and lifecycle of agent identity containers."""

    def __init__(self, get_db_fn, user_key_col: str = "user_api_key"):
        self.get_db = get_db_fn
        self.user_key_col = user_key_col

    def create_container(
        self,
        owner_api_key: str,
        agent_name: str,
        agent_type: str,
        mission: str = "",
        daemon_id: str = None,
        permissions: list[str] = None,
        wallet_budget_usd: float = 0.0,
        spending_limit_per_action: float = 10.0,
        credentials: dict = None,
    ) -> AgentIdentity:
        """Create a new isolated identity container for an agent."""
        container_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Generate deterministic email alias
        slug = agent_name.lower().replace(" ", "-").replace("_", "-")
        short_id = container_id[:8]
        email_alias = f"agent-{slug}-{short_id}@agents.swarmsfall.com"

        default_permissions = permissions or ["read", "write", "search"]
        default_credentials = credentials or {}

        identity = AgentIdentity({
            "container_id": container_id,
            "daemon_id": daemon_id,
            "owner_api_key": owner_api_key,
            "agent_name": agent_name,
            "agent_type": agent_type,
            "mission": mission,
            "email_alias": email_alias,
            "credentials": json.dumps(default_credentials),
            "permissions": json.dumps(default_permissions),
            "wallet_budget_usd": wallet_budget_usd,
            "wallet_spent_usd": 0.0,
            "spending_limit_per_action": spending_limit_per_action,
            "active": True,
            "created_at": now,
            "last_used_at": now,
        })

        conn = self.get_db()
        try:
            conn.execute(
                """INSERT INTO agent_identity (
                    container_id, daemon_id, owner_api_key, agent_name, agent_type,
                    mission, email_alias, credentials, permissions,
                    wallet_budget_usd, wallet_spent_usd, spending_limit_per_action,
                    active, created_at, last_used_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    container_id, daemon_id, owner_api_key, agent_name, agent_type,
                    mission, email_alias,
                    json.dumps(default_credentials),
                    json.dumps(default_permissions),
                    wallet_budget_usd, 0.0, spending_limit_per_action,
                    1, now, now,
                )
            )
            conn.commit()
            logger.info(f"🆔 Created identity container {container_id[:8]} for {agent_name}")
        finally:
            conn.close()

        return identity

    def get_by_daemon(self, daemon_id: str) -> Optional[AgentIdentity]:
        """Get identity container for a daemon."""
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT * FROM agent_identity WHERE daemon_id = ? AND active = 1",
                (daemon_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_identity(row, conn)
        finally:
            conn.close()

    def get_by_id(self, container_id: str) -> Optional[AgentIdentity]:
        """Get identity container by ID."""
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT * FROM agent_identity WHERE container_id = ?",
                (container_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_identity(row, conn)
        finally:
            conn.close()

    def list_containers(self, owner_api_key: str) -> list[AgentIdentity]:
        """List all identity containers for an owner."""
        conn = self.get_db()
        try:
            rows = conn.execute(
                f"SELECT * FROM agent_identity WHERE {self.user_key_col} = ? ORDER BY created_at DESC",
                (owner_api_key,)
            ).fetchall()
            return [self._row_to_identity(r, conn) for r in rows]
        finally:
            conn.close()

    def add_credential(self, container_id: str, service: str, credential_data: dict) -> bool:
        """Add a credential to an agent's container."""
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT credentials FROM agent_identity WHERE container_id = ?",
                (container_id,)
            ).fetchone()
            if not row:
                return False
            creds = json.loads(row[0] or "{}")
            creds[service] = credential_data
            conn.execute(
                "UPDATE agent_identity SET credentials = ?, last_used_at = ? WHERE container_id = ?",
                (json.dumps(creds), datetime.now(timezone.utc).isoformat(), container_id)
            )
            conn.commit()
            logger.info(f"🔑 Added {service} credential to container {container_id[:8]}")
            return True
        finally:
            conn.close()

    def update_permissions(self, container_id: str, permissions: list[str]) -> bool:
        """Update an agent's permission scopes."""
        conn = self.get_db()
        try:
            conn.execute(
                "UPDATE agent_identity SET permissions = ?, last_used_at = ? WHERE container_id = ?",
                (json.dumps(permissions), datetime.now(timezone.utc).isoformat(), container_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def fund_wallet(self, container_id: str, amount_usd: float) -> float:
        """Add funds to an agent's wallet. Returns new balance."""
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT wallet_budget_usd FROM agent_identity WHERE container_id = ?",
                (container_id,)
            ).fetchone()
            if not row:
                return 0.0
            new_budget = row[0] + amount_usd
            conn.execute(
                "UPDATE agent_identity SET wallet_budget_usd = ? WHERE container_id = ?",
                (new_budget, container_id)
            )
            conn.commit()
            logger.info(f"💰 Funded container {container_id[:8]}: +${amount_usd:.2f} (total: ${new_budget:.2f})")
            return new_budget
        finally:
            conn.close()

    def record_spend(self, container_id: str, amount_usd: float, description: str = "") -> bool:
        """Record spending from an agent's wallet. Returns False if insufficient funds."""
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT wallet_budget_usd, wallet_spent_usd, spending_limit_per_action FROM agent_identity WHERE container_id = ?",
                (container_id,)
            ).fetchone()
            if not row:
                return False
            budget, spent, limit = row
            if amount_usd > limit:
                logger.warning(f"🚫 Spend blocked for {container_id[:8]}: ${amount_usd:.2f} exceeds limit ${limit:.2f}")
                return False
            if (spent + amount_usd) > budget:
                logger.warning(f"🚫 Spend blocked for {container_id[:8]}: insufficient wallet balance")
                return False
            conn.execute(
                "UPDATE agent_identity SET wallet_spent_usd = wallet_spent_usd + ? WHERE container_id = ?",
                (amount_usd, container_id)
            )
            conn.commit()
            logger.info(f"💸 Spend recorded {container_id[:8]}: ${amount_usd:.2f} — {description}")
            return True
        finally:
            conn.close()

    def deactivate(self, container_id: str) -> bool:
        """Deactivate (soft-delete) an identity container."""
        conn = self.get_db()
        try:
            conn.execute(
                "UPDATE agent_identity SET active = 0 WHERE container_id = ?",
                (container_id,)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def _row_to_identity(self, row, conn) -> AgentIdentity:
        """Convert DB row to AgentIdentity. Handles both sqlite3.Row and tuple."""
        try:
            cols = [d[0] for d in conn.execute("SELECT * FROM agent_identity LIMIT 0").description]
            data = dict(zip(cols, row))
        except Exception:
            # Fallback positional mapping
            keys = ["container_id","daemon_id","owner_api_key","agent_name","agent_type",
                    "mission","email_alias","credentials","permissions",
                    "wallet_budget_usd","wallet_spent_usd","spending_limit_per_action",
                    "active","created_at","last_used_at"]
            data = dict(zip(keys, row))
        return AgentIdentity(data)


# ─── PERMISSION SCOPES ────────────────────────────────────

PERMISSION_SCOPES = {
    "read":         "Read data, search web, analyze information",
    "write":        "Create content, write files, post to owned channels",
    "search":       "Web search and data retrieval",
    "email":        "Send emails from agent's alias",
    "stripe":       "Create invoices and receive payments (agent's Stripe only)",
    "social":       "Post to agent's social accounts",
    "trade":        "Execute trades on prediction markets (within wallet limit)",
    "hire":         "Delegate tasks to sub-agents",
    "code":         "Write and execute code in sandbox",
    "admin":        "Full access — use with caution",
}

# Preset permission bundles
PERMISSION_PRESETS = {
    "researcher":   ["read", "search"],
    "writer":       ["read", "write", "search", "social"],
    "trader":       ["read", "search", "trade"],
    "operator":     ["read", "write", "search", "email", "hire"],
    "ceo":          ["read", "write", "search", "email", "stripe", "social", "trade", "hire", "code"],
}
