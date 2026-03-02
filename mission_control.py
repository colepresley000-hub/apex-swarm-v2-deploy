"""
APEX SWARM - Mission Control Module
====================================
Real-time God-eye visibility into all agent operations.

Features:
  1. Event Bus — Central pub/sub for all agent activity
  2. SSE Stream — Server-Sent Events for real-time dashboard updates
  3. Telegram Mission Control — Live activity feed with inline actions
  4. Daemon Agents — Persistent observe → decide → act loops
  5. Activity Log — Searchable history of all agent events

File: mission_control.py
"""

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("apex-swarm")


# ─── EVENT TYPES ──────────────────────────────────────────

class EventType(str, Enum):
    # Agent lifecycle
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"

    # Tool usage
    TOOL_CALLED = "tool.called"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"

    # Chain / Collab
    CHAIN_STARTED = "chain.started"
    CHAIN_STEP = "chain.step"
    CHAIN_COMPLETED = "chain.completed"
    COLLAB_STARTED = "collab.started"
    COLLAB_PARALLEL = "collab.parallel"
    COLLAB_SYNTHESIS = "collab.synthesis"
    COLLAB_COMPLETED = "collab.completed"

    # Daemon agents
    DAEMON_STARTED = "daemon.started"
    DAEMON_CYCLE = "daemon.cycle"
    DAEMON_ALERT = "daemon.alert"
    DAEMON_STOPPED = "daemon.stopped"

    # Schedule
    SCHEDULE_FIRED = "schedule.fired"

    # System
    SYSTEM_INFO = "system.info"
    SYSTEM_ERROR = "system.error"


# ─── EVENT ────────────────────────────────────────────────

@dataclass
class Event:
    event_type: str
    agent_id: str = ""
    agent_type: str = ""
    agent_name: str = ""
    message: str = ""
    data: dict = field(default_factory=dict)
    timestamp: str = ""
    event_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.event_id:
            self.event_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "agent_id": self.agent_id[:8] if self.agent_id else "",
            "agent_type": self.agent_type,
            "agent_name": self.agent_name,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        data = json.dumps(self.to_dict())
        return f"event: {self.event_type}\ndata: {data}\n\n"

    def to_telegram(self) -> str:
        """Format as Telegram message."""
        icons = {
            "agent.started": "🚀",
            "agent.completed": "✅",
            "agent.failed": "❌",
            "tool.called": "🔧",
            "tool.result": "📊",
            "tool.error": "⚠️",
            "chain.started": "🔗",
            "chain.step": "➡️",
            "chain.completed": "🏁",
            "collab.started": "🧠",
            "collab.parallel": "⚡",
            "collab.synthesis": "🔬",
            "collab.completed": "🏁",
            "daemon.started": "👁️",
            "daemon.cycle": "🔄",
            "daemon.alert": "🚨",
            "daemon.stopped": "⏹️",
            "schedule.fired": "⏰",
            "system.info": "ℹ️",
            "system.error": "🔴",
        }
        icon = icons.get(self.event_type, "📡")
        agent_label = f"*{self.agent_name}*" if self.agent_name else f"`{self.agent_type}`"

        if self.event_type == EventType.AGENT_STARTED:
            return f"{icon} {agent_label} started\n_{self.message[:200]}_"
        elif self.event_type == EventType.AGENT_COMPLETED:
            preview = self.data.get("result_preview", "")
            return f"{icon} {agent_label} completed\n{preview}"
        elif self.event_type == EventType.AGENT_FAILED:
            return f"{icon} {agent_label} FAILED\n`{self.message[:200]}`"
        elif self.event_type == EventType.TOOL_CALLED:
            tool = self.data.get("tool", "")
            args = self.data.get("args_preview", "")
            return f"{icon} {agent_label} → `{tool}({args})`"
        elif self.event_type == EventType.TOOL_RESULT:
            preview = self.data.get("result_preview", "")
            return f"{icon} Tool result: {preview[:150]}"
        elif self.event_type == EventType.DAEMON_ALERT:
            return f"{icon} *ALERT* from {agent_label}\n{self.message}"
        elif self.event_type == EventType.DAEMON_CYCLE:
            return f"{icon} {agent_label} cycle #{self.data.get('cycle', '?')}"
        elif self.event_type == EventType.CHAIN_STARTED:
            return f"{icon} Pipeline started: *{self.data.get('pipeline_name', 'Custom')}*\n_{self.message[:200]}_"
        elif self.event_type == EventType.CHAIN_COMPLETED:
            return f"{icon} Pipeline complete: *{self.data.get('pipeline_name', 'Custom')}*"
        elif self.event_type == EventType.SCHEDULE_FIRED:
            return f"{icon} Schedule fired: {agent_label}\n_{self.message[:200]}_"
        else:
            return f"{icon} [{self.event_type}] {agent_label}: {self.message[:200]}"


# ─── EVENT BUS ────────────────────────────────────────────

class EventBus:
    """Central event bus for all agent activity. Supports SSE subscribers and Telegram forwarding."""

    def __init__(self, max_history: int = 500):
        self._subscribers: list[asyncio.Queue] = []
        self._history: deque[Event] = deque(maxlen=max_history)
        self._telegram_chat_ids: set[int] = set()
        self._telegram_send_fn: Optional[Callable] = None
        self._telegram_verbosity: str = "important"  # "all", "important", "alerts_only"
        self._stats = {
            "total_events": 0,
            "events_by_type": {},
            "active_agents": {},
            "active_daemons": {},
        }

    def set_telegram(self, send_fn: Callable, chat_ids: set[int] = None, verbosity: str = "important"):
        """Configure Telegram forwarding."""
        self._telegram_send_fn = send_fn
        if chat_ids:
            self._telegram_chat_ids = chat_ids
        self._telegram_verbosity = verbosity

    def add_telegram_chat(self, chat_id: int):
        self._telegram_chat_ids.add(chat_id)

    def remove_telegram_chat(self, chat_id: int):
        self._telegram_chat_ids.discard(chat_id)

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to real-time events. Returns a queue that receives events."""
        q = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def emit(self, event: Event):
        """Emit an event to all subscribers, history, and Telegram."""
        self._history.append(event)
        self._stats["total_events"] += 1
        etype = event.event_type
        self._stats["events_by_type"][etype] = self._stats["events_by_type"].get(etype, 0) + 1

        # Track active agents
        if event.event_type == EventType.AGENT_STARTED:
            self._stats["active_agents"][event.agent_id] = {
                "type": event.agent_type,
                "name": event.agent_name,
                "started": event.timestamp,
            }
        elif event.event_type in (EventType.AGENT_COMPLETED, EventType.AGENT_FAILED):
            self._stats["active_agents"].pop(event.agent_id, None)

        # Track daemons
        if event.event_type == EventType.DAEMON_STARTED:
            self._stats["active_daemons"][event.agent_id] = {
                "type": event.agent_type,
                "name": event.agent_name,
                "started": event.timestamp,
                "cycles": 0,
            }
        elif event.event_type == EventType.DAEMON_CYCLE:
            if event.agent_id in self._stats["active_daemons"]:
                self._stats["active_daemons"][event.agent_id]["cycles"] = event.data.get("cycle", 0)
        elif event.event_type == EventType.DAEMON_STOPPED:
            self._stats["active_daemons"].pop(event.agent_id, None)

        # Push to SSE subscribers
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

        # Forward to Telegram
        if self._telegram_send_fn and self._telegram_chat_ids:
            if self._should_send_telegram(event):
                msg = event.to_telegram()
                for chat_id in self._telegram_chat_ids:
                    try:
                        await self._telegram_send_fn(chat_id, msg)
                    except Exception as e:
                        logger.error(f"Telegram forward failed: {e}")

    def _should_send_telegram(self, event: Event) -> bool:
        """Filter events based on verbosity level."""
        if self._telegram_verbosity == "all":
            return True
        elif self._telegram_verbosity == "alerts_only":
            return event.event_type in (
                EventType.DAEMON_ALERT,
                EventType.AGENT_FAILED,
                EventType.SYSTEM_ERROR,
            )
        else:  # "important"
            return event.event_type in (
                EventType.AGENT_STARTED,
                EventType.AGENT_COMPLETED,
                EventType.AGENT_FAILED,
                EventType.CHAIN_STARTED,
                EventType.CHAIN_COMPLETED,
                EventType.COLLAB_STARTED,
                EventType.COLLAB_COMPLETED,
                EventType.DAEMON_STARTED,
                EventType.DAEMON_ALERT,
                EventType.DAEMON_STOPPED,
                EventType.SCHEDULE_FIRED,
                EventType.SYSTEM_ERROR,
            )

    def get_history(self, limit: int = 50, event_type: str = None) -> list[dict]:
        """Get recent event history."""
        events = list(self._history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in events[-limit:]]

    def get_stats(self) -> dict:
        return {
            "total_events": self._stats["total_events"],
            "events_by_type": dict(self._stats["events_by_type"]),
            "active_agents": len(self._stats["active_agents"]),
            "active_agents_detail": dict(self._stats["active_agents"]),
            "active_daemons": len(self._stats["active_daemons"]),
            "active_daemons_detail": dict(self._stats["active_daemons"]),
            "sse_subscribers": len(self._subscribers),
            "telegram_chats": len(self._telegram_chat_ids),
        }


# ─── GLOBAL EVENT BUS INSTANCE ───────────────────────────

event_bus = EventBus()


# ─── DAEMON AGENT MANAGER ────────────────────────────────

class DaemonManager:
    """Manages persistent agent loops (observe → decide → act)."""

    def __init__(self):
        self._daemons: dict[str, dict] = {}  # daemon_id → {task, config, ...}

    async def start_daemon(
        self,
        agent_type: str,
        agent_name: str,
        task_description: str,
        execute_fn: Callable,
        interval_seconds: int = 300,
        max_cycles: int = 0,
        alert_conditions: list[str] = None,
        user_api_key: str = "system",
    ) -> str:
        """Start a persistent daemon agent that runs on a loop."""
        daemon_id = str(uuid.uuid4())

        config = {
            "agent_type": agent_type,
            "agent_name": agent_name,
            "task_description": task_description,
            "interval_seconds": interval_seconds,
            "max_cycles": max_cycles,
            "alert_conditions": alert_conditions or [],
            "user_api_key": user_api_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        task = asyncio.create_task(
            self._daemon_loop(daemon_id, config, execute_fn)
        )

        self._daemons[daemon_id] = {
            "task": task,
            "config": config,
            "status": "running",
            "cycles": 0,
            "last_result": None,
        }

        await event_bus.emit(Event(
            event_type=EventType.DAEMON_STARTED,
            agent_id=daemon_id,
            agent_type=agent_type,
            agent_name=agent_name,
            message=f"Daemon started: {task_description[:200]}",
            data={"interval": interval_seconds, "max_cycles": max_cycles},
        ))

        return daemon_id

    async def _daemon_loop(self, daemon_id: str, config: dict, execute_fn: Callable):
        """The core daemon loop: observe → decide → act → sleep → repeat."""
        agent_type = config["agent_type"]
        agent_name = config["agent_name"]
        task_desc = config["task_description"]
        interval = config["interval_seconds"]
        max_cycles = config["max_cycles"]
        alert_conditions = config["alert_conditions"]
        cycle = 0

        try:
            while True:
                cycle += 1
                if daemon_id not in self._daemons:
                    break
                if max_cycles > 0 and cycle > max_cycles:
                    break

                self._daemons[daemon_id]["cycles"] = cycle

                # Build the daemon prompt with cycle context
                daemon_prompt = (
                    f"[DAEMON MODE - Cycle {cycle}]\n"
                    f"You are running as a persistent monitoring agent.\n"
                    f"Task: {task_desc}\n\n"
                    f"Instructions:\n"
                    f"1. Check current state/data relevant to this task\n"
                    f"2. Analyze if anything has changed or needs attention\n"
                    f"3. If you find something notable, clearly state: ALERT: <description>\n"
                    f"4. Provide a brief status update\n\n"
                    f"Previous cycle result: {self._daemons.get(daemon_id, {}).get('last_result', 'First cycle')}\n"
                )

                await event_bus.emit(Event(
                    event_type=EventType.DAEMON_CYCLE,
                    agent_id=daemon_id,
                    agent_type=agent_type,
                    agent_name=agent_name,
                    message=f"Cycle {cycle}",
                    data={"cycle": cycle},
                ))

                # Execute the agent
                agent_id = str(uuid.uuid4())
                try:
                    result = await execute_fn(agent_id, agent_type, daemon_prompt, config["user_api_key"])

                    if daemon_id in self._daemons:
                        self._daemons[daemon_id]["last_result"] = result[:500] if result else ""

                    # Check for alerts in the result
                    if result and "ALERT:" in result.upper():
                        await event_bus.emit(Event(
                            event_type=EventType.DAEMON_ALERT,
                            agent_id=daemon_id,
                            agent_type=agent_type,
                            agent_name=agent_name,
                            message=result[:500],
                            data={"cycle": cycle, "full_result": result[:2000]},
                        ))

                    # Check custom alert conditions
                    if result and alert_conditions:
                        for condition in alert_conditions:
                            if condition.lower() in result.lower():
                                await event_bus.emit(Event(
                                    event_type=EventType.DAEMON_ALERT,
                                    agent_id=daemon_id,
                                    agent_type=agent_type,
                                    agent_name=agent_name,
                                    message=f"Condition triggered: '{condition}'\n{result[:300]}",
                                    data={"cycle": cycle, "condition": condition},
                                ))

                except Exception as e:
                    logger.error(f"Daemon {daemon_id[:8]} cycle {cycle} error: {e}")
                    await event_bus.emit(Event(
                        event_type=EventType.SYSTEM_ERROR,
                        agent_id=daemon_id,
                        agent_type=agent_type,
                        agent_name=agent_name,
                        message=f"Daemon error cycle {cycle}: {str(e)}",
                    ))

                # Sleep until next cycle
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.emit(Event(
                event_type=EventType.DAEMON_STOPPED,
                agent_id=daemon_id,
                agent_type=agent_type,
                agent_name=agent_name,
                message=f"Daemon stopped after {cycle} cycles",
                data={"total_cycles": cycle},
            ))
            if daemon_id in self._daemons:
                self._daemons[daemon_id]["status"] = "stopped"

    async def stop_daemon(self, daemon_id: str) -> bool:
        """Stop a running daemon."""
        if daemon_id not in self._daemons:
            return False
        daemon = self._daemons[daemon_id]
        if daemon["task"] and not daemon["task"].done():
            daemon["task"].cancel()
            try:
                await daemon["task"]
            except asyncio.CancelledError:
                pass
        daemon["status"] = "stopped"
        return True

    def get_daemons(self) -> list[dict]:
        """List all daemons with their status."""
        result = []
        for did, d in self._daemons.items():
            result.append({
                "daemon_id": did,
                "agent_type": d["config"]["agent_type"],
                "agent_name": d["config"]["agent_name"],
                "task": d["config"]["task_description"][:200],
                "interval_seconds": d["config"]["interval_seconds"],
                "status": d["status"],
                "cycles": d["cycles"],
                "last_result_preview": (d["last_result"] or "")[:200],
                "created_at": d["config"]["created_at"],
            })
        return result

    def get_daemon(self, daemon_id: str) -> Optional[dict]:
        if daemon_id not in self._daemons:
            return None
        d = self._daemons[daemon_id]
        return {
            "daemon_id": daemon_id,
            "config": d["config"],
            "status": d["status"],
            "cycles": d["cycles"],
            "last_result": d["last_result"],
        }


# ─── GLOBAL DAEMON MANAGER ───────────────────────────────

daemon_manager = DaemonManager()


# ─── PRESET DAEMON CONFIGS ───────────────────────────────

DAEMON_PRESETS = {
    "crypto-monitor": {
        "name": "Crypto Market Monitor",
        "agent_type": "research",
        "description": "Monitor crypto markets for significant price movements and news",
        "task_description": "Check the current state of the crypto market. Look for: significant price movements (>5% in 24h) in BTC, ETH, SOL, and top tokens. Check for breaking news, whale movements, or exchange anomalies. Report only notable findings.",
        "interval_seconds": 300,
        "alert_conditions": ["crash", "pump", "hack", "exploit", "whale", "liquidation", "breaking"],
    },
    "defi-yield-scanner": {
        "name": "DeFi Yield Scanner",
        "agent_type": "yield-hunter",
        "description": "Continuously scan for high-yield DeFi opportunities",
        "task_description": "Scan DeFi protocols across Ethereum, Arbitrum, Base, and Solana for yield opportunities above 8% APY. Check TVL stability, protocol reputation, and smart contract audit status. Report any new high-yield opportunities or significant changes.",
        "interval_seconds": 600,
        "alert_conditions": ["high yield", "new opportunity", "risk", "depeg", "exploit"],
    },
    "news-sentinel": {
        "name": "News Sentinel",
        "agent_type": "research",
        "description": "Monitor breaking news in crypto, AI, and tech",
        "task_description": "Check for breaking news and developments in crypto, AI agents, and tech. Focus on: regulatory actions, major product launches, significant funding rounds, security incidents, and market-moving events. Report only genuinely new and important items.",
        "interval_seconds": 900,
        "alert_conditions": ["breaking", "urgent", "regulation", "ban", "SEC", "hack"],
    },
    "whale-watcher": {
        "name": "Whale Watcher",
        "agent_type": "whale-tracker",
        "description": "Track large wallet movements and smart money",
        "task_description": "Monitor large wallet movements for BTC, ETH, and top tokens. Look for: unusual exchange inflows/outflows, wallet accumulation patterns, dormant wallet activations, and smart money positioning. Report notable movements.",
        "interval_seconds": 600,
        "alert_conditions": ["large transfer", "exchange inflow", "accumulation", "dump", "whale"],
    },
    "competitor-tracker": {
        "name": "Competitor Tracker",
        "agent_type": "ai-landscape",
        "description": "Monitor AI agent ecosystem for new launches and trends",
        "task_description": "Check for new developments in the AI agent ecosystem. Monitor: new agent platforms, MCP integrations, framework updates, notable GitHub repos, product launches, and funding. Focus on what's gaining real traction vs hype.",
        "interval_seconds": 3600,
        "alert_conditions": ["launch", "trending", "viral", "funding", "acquisition"],
    },
}
