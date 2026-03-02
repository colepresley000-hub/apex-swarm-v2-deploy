"""
APEX SWARM - Swarm Memory Module
=================================
Shared memory system that lets agents learn from each other.

Agents write discoveries, insights, and results to shared memory.
Other agents can query relevant memories before executing tasks.
This is what makes a swarm smarter than individual agents.

Features:
  1. Auto-extraction — Key findings extracted from agent results
  2. TF-IDF relevance scoring — Query memories by similarity
  3. Decay — Old memories fade, recent ones rank higher
  4. Namespaces — Memories scoped by domain (crypto, code, research, etc.)
  5. Cross-agent — Any agent can read memories from any other agent

File: swarm_memory.py
"""

import json
import logging
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("apex-swarm")


# ─── TEXT PROCESSING ──────────────────────────────────────

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "no", "not", "only", "same", "so",
    "than", "too", "very", "just", "because", "but", "and", "or", "if",
    "while", "this", "that", "these", "those", "i", "you", "he", "she",
    "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "its", "our", "their", "what", "which", "who", "whom",
}


def tokenize(text: str) -> list[str]:
    """Simple tokenizer — lowercase, strip punctuation, remove stop words."""
    words = re.findall(r'[a-z0-9]+', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]


def extract_key_phrases(text: str, top_n: int = 10) -> list[str]:
    """Extract most significant phrases from text."""
    tokens = tokenize(text)
    # Bigrams
    bigrams = [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens)-1)]
    # Count frequencies
    counts = Counter(tokens + bigrams)
    # Return top phrases
    return [phrase for phrase, _ in counts.most_common(top_n)]


def compute_similarity(query_tokens: list[str], memory_tokens: list[str]) -> float:
    """Compute Jaccard + weighted overlap similarity."""
    if not query_tokens or not memory_tokens:
        return 0.0
    q_set = set(query_tokens)
    m_set = set(memory_tokens)
    intersection = q_set & m_set
    union = q_set | m_set
    if not union:
        return 0.0
    jaccard = len(intersection) / len(union)
    # Weight by how many query terms matched
    coverage = len(intersection) / len(q_set) if q_set else 0
    return (jaccard * 0.4) + (coverage * 0.6)


def recency_score(created_at: str, half_life_hours: float = 48.0) -> float:
    """Exponential decay — recent memories rank higher."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_old = (now - created).total_seconds() / 3600
        return math.exp(-0.693 * hours_old / half_life_hours)
    except Exception:
        return 0.5


# ─── MEMORY MANAGER ──────────────────────────────────────

class SwarmMemory:
    """Shared memory system for the agent swarm."""

    def __init__(self, db_fn, db_execute_fn, db_fetchall_fn, db_fetchone_fn, user_key_col: str = "user_api_key"):
        self._db_fn = db_fn
        self._db_execute = db_execute_fn
        self._db_fetchall = db_fetchall_fn
        self._db_fetchone = db_fetchone_fn
        self._user_key_col = user_key_col

    def init_tables(self, conn):
        """Create memory tables if they don't exist."""
        # Check if it's postgres
        is_pg = hasattr(conn, 'autocommit')
        if is_pg:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS swarm_memory (
                    id TEXT PRIMARY KEY,
                    user_api_key TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    source_agent_name TEXT DEFAULT '',
                    namespace TEXT DEFAULT 'general',
                    content TEXT NOT NULL,
                    key_phrases TEXT DEFAULT '[]',
                    tokens TEXT DEFAULT '[]',
                    importance REAL DEFAULT 0.5,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_user ON swarm_memory(user_api_key);
                CREATE INDEX IF NOT EXISTS idx_memory_namespace ON swarm_memory(namespace);
                CREATE INDEX IF NOT EXISTS idx_memory_source ON swarm_memory(source_agent);
            """)
            conn.commit()
        else:
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS swarm_memory (
                    id TEXT PRIMARY KEY,
                    {self._user_key_col} TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    source_agent_name TEXT DEFAULT '',
                    namespace TEXT DEFAULT 'general',
                    content TEXT NOT NULL,
                    key_phrases TEXT DEFAULT '[]',
                    tokens TEXT DEFAULT '[]',
                    importance REAL DEFAULT 0.5,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_namespace ON swarm_memory(namespace);
                CREATE INDEX IF NOT EXISTS idx_memory_source ON swarm_memory(source_agent);
            """)
            try:
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_memory_user ON swarm_memory({self._user_key_col})")
            except Exception:
                pass
            conn.commit()

    async def store(
        self,
        content: str,
        source_agent: str,
        source_agent_name: str = "",
        namespace: str = "general",
        user_api_key: str = "system",
        importance: float = 0.5,
    ) -> str:
        """Store a memory entry from an agent."""
        if len(content.strip()) < 20:
            return ""  # Skip trivial content

        memory_id = str(uuid.uuid4())
        tokens = tokenize(content)
        key_phrases = extract_key_phrases(content)
        now = datetime.now(timezone.utc).isoformat()

        # Truncate content to keep DB manageable
        stored_content = content[:2000] if len(content) > 2000 else content

        conn = self._db_fn()
        try:
            self._db_execute(conn,
                f"INSERT INTO swarm_memory (id, {self._user_key_col}, source_agent, source_agent_name, namespace, content, key_phrases, tokens, importance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (memory_id, user_api_key, source_agent, source_agent_name, namespace, stored_content,
                 json.dumps(key_phrases), json.dumps(tokens[:100]), importance, now),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Memory store failed: {e}")
            return ""
        finally:
            conn.close()

        return memory_id

    async def query(
        self,
        query_text: str,
        namespace: str = None,
        user_api_key: str = "system",
        limit: int = 5,
        min_score: float = 0.1,
    ) -> list[dict]:
        """Query memories by relevance to a text query."""
        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []

        conn = self._db_fn()
        try:
            if namespace:
                rows = self._db_fetchall(conn,
                    f"SELECT id, source_agent, source_agent_name, namespace, content, tokens, importance, created_at FROM swarm_memory WHERE {self._user_key_col} = ? AND namespace = ? ORDER BY created_at DESC LIMIT 200",
                    (user_api_key, namespace),
                )
            else:
                rows = self._db_fetchall(conn,
                    f"SELECT id, source_agent, source_agent_name, namespace, content, tokens, importance, created_at FROM swarm_memory WHERE {self._user_key_col} = ? ORDER BY created_at DESC LIMIT 200",
                    (user_api_key,),
                )
        finally:
            conn.close()

        if not rows:
            return []

        # Score each memory
        scored = []
        for row in rows:
            mid, src_agent, src_name, ns, content, tokens_json, importance, created_at = row
            try:
                mem_tokens = json.loads(tokens_json) if tokens_json else tokenize(content)
            except Exception:
                mem_tokens = tokenize(content)

            sim = compute_similarity(query_tokens, mem_tokens)
            recency = recency_score(created_at)
            # Combined score: similarity (60%) + recency (25%) + importance (15%)
            score = (sim * 0.6) + (recency * 0.25) + (importance * 0.15)

            if score >= min_score:
                scored.append({
                    "memory_id": mid,
                    "source_agent": src_agent,
                    "source_agent_name": src_name,
                    "namespace": ns,
                    "content": content,
                    "score": round(score, 4),
                    "similarity": round(sim, 4),
                    "recency": round(recency, 4),
                    "created_at": created_at,
                })

        # Sort by score, return top N
        scored.sort(key=lambda x: x["score"], reverse=True)

        # Update access counts for returned memories
        if scored:
            conn = self._db_fn()
            try:
                now = datetime.now(timezone.utc).isoformat()
                for m in scored[:limit]:
                    try:
                        self._db_execute(conn,
                            "UPDATE swarm_memory SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                            (now, m["memory_id"]),
                        )
                    except Exception:
                        pass
                conn.commit()
            finally:
                conn.close()

        return scored[:limit]

    def format_for_prompt(self, memories: list[dict]) -> str:
        """Format memories for injection into agent system prompt."""
        if not memories:
            return ""
        lines = ["\n\n## Swarm Memory (shared knowledge from other agents):\n"]
        for m in memories:
            src = m["source_agent_name"] or m["source_agent"]
            score = m["score"]
            lines.append(f"**[{src}]** (relevance: {score:.0%})\n{m['content'][:500]}\n---")
        return "\n".join(lines)

    async def auto_extract_and_store(
        self,
        result: str,
        agent_type: str,
        agent_name: str,
        task_description: str,
        user_api_key: str = "system",
    ) -> list[str]:
        """Automatically extract and store key findings from an agent result."""
        if not result or len(result) < 50:
            return []

        # Determine namespace from agent category
        namespace_map = {
            "research": "crypto", "token-analysis": "crypto", "defi": "crypto",
            "onchain-analyst": "crypto", "whale-tracker": "crypto", "portfolio-manager": "crypto",
            "macro-analyst": "macro", "yield-hunter": "crypto",
            "fullstack-dev": "code", "code-reviewer": "code", "python-dev": "code",
            "js-dev": "code", "solidity-dev": "code", "security-analyst": "security",
            "mcp-architect": "code", "agent-orchestrator": "code",
            "market-researcher": "research", "financial-analyst": "research",
            "trend-analyst": "research", "competitor-analyst": "research",
            "ai-landscape": "research",
            "data-analyst": "data", "web-scraper": "data",
        }
        namespace = namespace_map.get(agent_type, "general")

        # Calculate importance based on content signals
        importance = 0.5
        important_signals = ["alert", "breaking", "significant", "critical", "important", "key finding", "notable"]
        for signal in important_signals:
            if signal in result.lower():
                importance = min(importance + 0.1, 1.0)

        stored_ids = []

        # Store the full result as a memory (truncated)
        mid = await self.store(
            content=f"Task: {task_description[:200]}\n\nResult: {result[:1500]}",
            source_agent=agent_type,
            source_agent_name=agent_name,
            namespace=namespace,
            user_api_key=user_api_key,
            importance=importance,
        )
        if mid:
            stored_ids.append(mid)

        return stored_ids

    async def get_stats(self, user_api_key: str = "system") -> dict:
        """Get memory stats."""
        conn = self._db_fn()
        try:
            total = self._db_fetchone(conn,
                f"SELECT COUNT(*) FROM swarm_memory WHERE {self._user_key_col} = ?",
                (user_api_key,),
            )
            by_ns = self._db_fetchall(conn,
                f"SELECT namespace, COUNT(*) FROM swarm_memory WHERE {self._user_key_col} = ? GROUP BY namespace",
                (user_api_key,),
            )
            by_agent = self._db_fetchall(conn,
                f"SELECT source_agent, COUNT(*) FROM swarm_memory WHERE {self._user_key_col} = ? GROUP BY source_agent ORDER BY COUNT(*) DESC LIMIT 10",
                (user_api_key,),
            )
        finally:
            conn.close()

        return {
            "total_memories": total[0] if total else 0,
            "by_namespace": {r[0]: r[1] for r in by_ns} if by_ns else {},
            "by_agent": {r[0]: r[1] for r in by_agent} if by_agent else {},
        }

    async def cleanup(self, user_api_key: str = "system", max_age_days: int = 30, max_entries: int = 1000):
        """Clean up old, low-importance memories."""
        conn = self._db_fn()
        try:
            # Delete old low-importance memories
            self._db_execute(conn,
                f"DELETE FROM swarm_memory WHERE {self._user_key_col} = ? AND importance < 0.3 AND created_at < datetime('now', '-' || ? || ' days')",
                (user_api_key, max_age_days),
            )
            # Keep only the most recent N entries
            self._db_execute(conn,
                f"DELETE FROM swarm_memory WHERE {self._user_key_col} = ? AND id NOT IN (SELECT id FROM swarm_memory WHERE {self._user_key_col} = ? ORDER BY created_at DESC LIMIT ?)",
                (user_api_key, user_api_key, max_entries),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Memory cleanup failed: {e}")
        finally:
            conn.close()
