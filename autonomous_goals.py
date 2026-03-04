"""
APEX SWARM - Autonomous Goal System
======================================
Give the swarm a high-level goal. It builds the org, assigns roles,
decomposes into projects → tasks, executes autonomously, reports back.

Like ZHC/Paperclip but as an API, not a separate product.

Features:
  1. Goals — high-level objectives ("Launch a SaaS product", "Run a crypto fund")
  2. Org Chart — role-based agent hierarchy with permissions
  3. Projects — goals decompose into projects with timelines
  4. Tasks — projects decompose into agent-executable tasks
  5. Role Permissions — CEO gets all tools, Writer gets limited
  6. Budget Tracking — token/cost budget per goal
  7. Progress Reports — automated status updates
  8. Cycles — recurring execution (daily standup, weekly review)

File: autonomous_goals.py
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Callable

logger = logging.getLogger("apex-swarm")


# ─── ROLE DEFINITIONS & PERMISSIONS ──────────────────────

ROLES = {
    "ceo": {
        "name": "CEO",
        "icon": "👔",
        "description": "Chief Executive — full access, strategic decisions, delegates everything",
        "agent_type": "research",
        "tools": ["web_search", "fetch_url", "crypto_prices", "run_code", "json_api",
                  "data_transform", "sentiment_analysis", "generate_chart", "rss_feed",
                  "send_webhook", "send_email", "screenshot_url"],
        "can_delegate": True,
        "can_hire": True,
        "can_fire": True,
        "budget_authority": True,
    },
    "cto": {
        "name": "CTO",
        "icon": "💻",
        "description": "Chief Technology — code review, architecture, technical decisions",
        "agent_type": "code-reviewer",
        "tools": ["web_search", "fetch_url", "run_code", "json_api", "data_transform", "screenshot_url"],
        "can_delegate": True,
        "can_hire": True,
        "can_fire": False,
        "budget_authority": False,
    },
    "cmo": {
        "name": "CMO",
        "icon": "📢",
        "description": "Chief Marketing — content, social, SEO, growth",
        "agent_type": "social-media",
        "tools": ["web_search", "fetch_url", "sentiment_analysis", "rss_feed",
                  "send_webhook", "send_email", "generate_chart"],
        "can_delegate": True,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
    "cfo": {
        "name": "CFO",
        "icon": "💰",
        "description": "Chief Financial — budgets, costs, financial analysis",
        "agent_type": "data-analyst",
        "tools": ["web_search", "fetch_url", "crypto_prices", "run_code",
                  "data_transform", "generate_chart", "json_api"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": True,
    },
    "researcher": {
        "name": "Researcher",
        "icon": "🔬",
        "description": "Deep research, analysis, data gathering",
        "agent_type": "research",
        "tools": ["web_search", "fetch_url", "run_code", "data_transform",
                  "sentiment_analysis", "rss_feed"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
    "writer": {
        "name": "Writer",
        "icon": "✍️",
        "description": "Content creation — blogs, copy, social, docs",
        "agent_type": "blog-writer",
        "tools": ["web_search", "fetch_url", "send_email"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
    "analyst": {
        "name": "Analyst",
        "icon": "📊",
        "description": "Data analysis, reporting, metrics",
        "agent_type": "data-analyst",
        "tools": ["web_search", "fetch_url", "crypto_prices", "run_code",
                  "data_transform", "generate_chart", "json_api"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
    "marketer": {
        "name": "Marketer",
        "icon": "📣",
        "description": "Marketing execution — ads, email, campaigns",
        "agent_type": "copywriter",
        "tools": ["web_search", "fetch_url", "sentiment_analysis",
                  "send_email", "send_webhook"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
    "support": {
        "name": "Support",
        "icon": "🎧",
        "description": "Customer support, FAQ, issue resolution",
        "agent_type": "summarizer",
        "tools": ["web_search", "fetch_url", "send_email"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
    "security": {
        "name": "Security",
        "icon": "🔒",
        "description": "Security audits, vulnerability scanning, compliance",
        "agent_type": "code-reviewer",
        "tools": ["web_search", "fetch_url", "run_code", "json_api"],
        "can_delegate": False,
        "can_hire": False,
        "can_fire": False,
        "budget_authority": False,
    },
}

# ─── EMAIL PERMISSIONS PER ROLE ──────────────────────────

EMAIL_PERMISSIONS = {
    "ceo":        {"check_inbox": True, "read_email": True, "send_email": True, "reply_email": True, "forward_email": True, "delete_email": True, "manage_labels": True},
    "cto":        {"check_inbox": True, "read_email": True, "send_email": True, "reply_email": True, "forward_email": True, "delete_email": False, "manage_labels": False},
    "cmo":        {"check_inbox": True, "read_email": True, "send_email": True, "reply_email": True, "forward_email": True, "delete_email": False, "manage_labels": True},
    "cfo":        {"check_inbox": True, "read_email": True, "send_email": True, "reply_email": True, "forward_email": False, "delete_email": False, "manage_labels": False},
    "researcher": {"check_inbox": True, "read_email": True, "send_email": False, "reply_email": False, "forward_email": False, "delete_email": False, "manage_labels": False},
    "writer":     {"check_inbox": False, "read_email": True, "send_email": True, "reply_email": False, "forward_email": False, "delete_email": False, "manage_labels": False},
    "analyst":    {"check_inbox": True, "read_email": True, "send_email": False, "reply_email": False, "forward_email": False, "delete_email": False, "manage_labels": False},
    "marketer":   {"check_inbox": True, "read_email": True, "send_email": True, "reply_email": True, "forward_email": True, "delete_email": False, "manage_labels": True},
    "support":    {"check_inbox": True, "read_email": True, "send_email": True, "reply_email": True, "forward_email": True, "delete_email": False, "manage_labels": True},
    "security":   {"check_inbox": True, "read_email": True, "send_email": False, "reply_email": False, "forward_email": False, "delete_email": False, "manage_labels": False},
}


def get_tools_for_role(role_id: str) -> list:
    """Get allowed tools for a role."""
    role = ROLES.get(role_id)
    if not role:
        return []
    return role["tools"]


def check_email_permission(role_id: str, action: str) -> bool:
    """Check if a role can perform an email action."""
    perms = EMAIL_PERMISSIONS.get(role_id, {})
    return perms.get(action, False)


# ─── DATA MODELS ─────────────────────────────────────────

class Task:
    def __init__(self, task_id: str, title: str, description: str, role: str, project_id: str,
                 depends_on: list = None, priority: int = 1):
        self.task_id = task_id
        self.title = title
        self.description = description
        self.role = role
        self.project_id = project_id
        self.depends_on = depends_on or []
        self.priority = priority
        self.status = "pending"  # pending, running, completed, failed, blocked
        self.agent_id = None
        self.result = None
        self.cost = 0.0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.completed_at = None

    def to_dict(self):
        return {
            "task_id": self.task_id, "title": self.title, "description": self.description[:200],
            "role": self.role, "role_name": ROLES.get(self.role, {}).get("name", self.role),
            "role_icon": ROLES.get(self.role, {}).get("icon", "🤖"),
            "project_id": self.project_id, "depends_on": self.depends_on,
            "priority": self.priority, "status": self.status, "agent_id": self.agent_id,
            "result": self.result[:300] if self.result else None, "cost": self.cost,
        }


class Project:
    def __init__(self, project_id: str, title: str, description: str, goal_id: str):
        self.project_id = project_id
        self.title = title
        self.description = description
        self.goal_id = goal_id
        self.tasks: list[Task] = []
        self.status = "planning"  # planning, active, completed, failed
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        completed = sum(1 for t in self.tasks if t.status == "completed")
        return {
            "project_id": self.project_id, "title": self.title, "description": self.description[:200],
            "goal_id": self.goal_id, "status": self.status,
            "tasks_total": len(self.tasks), "tasks_completed": completed,
            "progress": round(completed / max(len(self.tasks), 1) * 100),
            "tasks": [t.to_dict() for t in self.tasks],
        }


class Goal:
    def __init__(self, goal_id: str, title: str, description: str, user_api_key: str,
                 budget_usd: float = 0.0, org_roles: list = None):
        self.goal_id = goal_id
        self.title = title
        self.description = description
        self.user_api_key = user_api_key
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        self.org_roles = org_roles or ["ceo", "researcher", "writer", "analyst"]
        self.projects: list[Project] = []
        self.status = "created"  # created, planning, running, completed, paused, failed
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.completed_at = None
        self.cycle_count = 0

    def to_dict(self):
        total_tasks = sum(len(p.tasks) for p in self.projects)
        completed_tasks = sum(sum(1 for t in p.tasks if t.status == "completed") for p in self.projects)
        return {
            "goal_id": self.goal_id, "title": self.title, "description": self.description[:300],
            "status": self.status, "budget_usd": self.budget_usd, "spent_usd": round(self.spent_usd, 4),
            "org_roles": self.org_roles,
            "org_chart": [{"role": r, **ROLES.get(r, {"name": r, "icon": "🤖"})} for r in self.org_roles],
            "projects": [p.to_dict() for p in self.projects],
            "projects_count": len(self.projects), "tasks_total": total_tasks,
            "tasks_completed": completed_tasks,
            "progress": round(completed_tasks / max(total_tasks, 1) * 100),
            "cycle_count": self.cycle_count, "created_at": self.created_at,
        }


# ─── PROMPTS ─────────────────────────────────────────────

GOAL_DECOMPOSE_PROMPT = """You are a strategic project planner for an autonomous AI company.
Given a high-level goal, decompose it into 2-4 concrete projects, each with 2-5 actionable tasks.

Available roles and their capabilities:
{roles}

Rules:
1. Each task must be assigned to ONE role
2. Tasks should be specific and independently executable
3. Mark dependencies between tasks (task B needs task A's output)
4. Think about what a real company would do — research first, then plan, then execute
5. Stay within the available roles

Respond ONLY with valid JSON:
{{
  "projects": [
    {{
      "title": "Project name",
      "description": "What this project achieves",
      "tasks": [
        {{
          "title": "Task name",
          "description": "Specific instructions for the agent",
          "role": "role_id",
          "depends_on": [],
          "priority": 1
        }}
      ]
    }}
  ]
}}"""


PROGRESS_REPORT_PROMPT = """You are a project manager generating a status report.

Goal: {goal_title}
Description: {goal_description}

Project results:
{results}

Generate a concise executive summary covering:
1. What was accomplished
2. Key findings or outputs
3. What's still pending
4. Recommended next steps"""


# ─── AUTONOMOUS GOAL ENGINE ──────────────────────────────

class GoalEngine:
    """Manages autonomous goal execution — decompose, assign, execute, report."""

    def __init__(self, agents: dict, execute_fn: Callable, llm_call_fn: Callable = None):
        self._agents = agents
        self._execute_fn = execute_fn
        self._llm_call_fn = llm_call_fn
        self._goals: dict[str, Goal] = {}
        self._get_db = None
        self._user_key_col = "user_api_key"

    def set_db(self, get_db_fn, user_key_col="user_api_key"):
        self._get_db = get_db_fn
        self._user_key_col = user_key_col

    async def create_goal(
        self,
        title: str,
        description: str,
        user_api_key: str,
        budget_usd: float = 0.0,
        org_roles: list = None,
        model: str = None,
        auto_execute: bool = True,
    ) -> Goal:
        """Create a goal, decompose it, optionally execute immediately."""
        goal_id = str(uuid.uuid4())[:12]
        goal = Goal(goal_id, title, description, user_api_key, budget_usd, org_roles)
        self._goals[goal_id] = goal

        # Decompose into projects and tasks
        goal.status = "planning"
        await self._decompose(goal, model)

        if auto_execute:
            goal.status = "running"
            await self._execute_goal(goal, model)
            goal.status = "completed"
            goal.completed_at = datetime.now(timezone.utc).isoformat()

        logger.info(f"🎯 Goal {goal_id} '{title}': {len(goal.projects)} projects, {sum(len(p.tasks) for p in goal.projects)} tasks → {goal.status}")
        return goal

    async def _decompose(self, goal: Goal, model: str = None):
        """Use LLM to decompose goal into projects and tasks."""
        roles_desc = "\n".join(
            f"  - {rid}: {r['name']} ({r['icon']}) — {r['description']}. Tools: {', '.join(r['tools'][:5])}"
            for rid, r in ROLES.items() if rid in goal.org_roles
        )
        prompt = GOAL_DECOMPOSE_PROMPT.replace("{roles}", roles_desc)

        if self._llm_call_fn:
            try:
                raw = await self._llm_call_fn(prompt, f"Goal: {goal.title}\n\nDescription: {goal.description}", model)
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
                parsed = json.loads(raw)

                for i, proj_data in enumerate(parsed.get("projects", [])[:4]):
                    proj_id = f"{goal.goal_id}-p{i+1}"
                    project = Project(proj_id, proj_data["title"], proj_data.get("description", ""), goal.goal_id)

                    for j, task_data in enumerate(proj_data.get("tasks", [])[:5]):
                        role = task_data.get("role", "researcher")
                        if role not in goal.org_roles:
                            role = goal.org_roles[0] if goal.org_roles else "researcher"
                        task = Task(
                            f"{proj_id}-t{j+1}", task_data["title"], task_data.get("description", ""),
                            role, proj_id, task_data.get("depends_on", []), task_data.get("priority", 1),
                        )
                        project.tasks.append(task)

                    goal.projects.append(project)
            except Exception as e:
                logger.error(f"Goal decomposition failed: {e}")

        # Fallback if decomposition failed
        if not goal.projects:
            proj = Project(f"{goal.goal_id}-p1", "Research & Execute", goal.description, goal.goal_id)
            proj.tasks.append(Task(f"{goal.goal_id}-p1-t1", "Research", f"Research: {goal.description}", "researcher", proj.project_id))
            proj.tasks.append(Task(f"{goal.goal_id}-p1-t2", "Analyze", f"Analyze findings about: {goal.description}", "analyst", proj.project_id, depends_on=[f"{goal.goal_id}-p1-t1"]))
            proj.tasks.append(Task(f"{goal.goal_id}-p1-t3", "Report", f"Write comprehensive report on: {goal.description}", "writer", proj.project_id, depends_on=[f"{goal.goal_id}-p1-t2"]))
            goal.projects.append(proj)

    async def _execute_goal(self, goal: Goal, model: str = None):
        """Execute all projects in a goal."""
        for project in goal.projects:
            project.status = "active"
            await self._execute_project(project, goal, model)
            completed = sum(1 for t in project.tasks if t.status == "completed")
            project.status = "completed" if completed == len(project.tasks) else "failed"
        goal.cycle_count += 1

    async def _execute_project(self, project: Project, goal: Goal, model: str = None):
        """Execute tasks in a project respecting dependencies."""
        completed_ids = set()
        max_rounds = len(project.tasks) + 2

        for _ in range(max_rounds):
            # Find ready tasks
            ready = [t for t in project.tasks
                     if t.status == "pending"
                     and all(d in completed_ids for d in t.depends_on)]
            if not ready:
                break

            # Inject dependency results
            for task in ready:
                dep_context = ""
                for dep_id in task.depends_on:
                    dep_task = next((t for t in project.tasks if t.task_id == dep_id), None)
                    if dep_task and dep_task.result:
                        dep_context += f"\n[{ROLES.get(dep_task.role, {}).get('name', dep_task.role)} output]: {dep_task.result[:1000]}\n"
                if dep_context:
                    task.description += f"\n\nContext from previous team members:{dep_context}"

            # Execute ready tasks in parallel
            await asyncio.gather(*[self._run_task(t, goal, model) for t in ready], return_exceptions=True)

            for t in ready:
                if t.status == "completed":
                    completed_ids.add(t.task_id)

    async def _run_task(self, task: Task, goal: Goal, model: str = None):
        """Execute a single task using the appropriate role's agent."""
        role = ROLES.get(task.role, ROLES.get("researcher"))
        agent_type = role["agent_type"]
        agent_id = str(uuid.uuid4())
        task.agent_id = agent_id
        task.status = "running"

        # Build role-aware system prefix
        role_prefix = f"You are the {role['name']} ({role['icon']}) at an autonomous AI company.\nYour goal: {goal.title}\nYour task: {task.title}\n\n"
        full_task = role_prefix + task.description

        try:
            if self._get_db:
                now = datetime.now(timezone.utc).isoformat()
                conn = self._get_db()
                try:
                    conn.execute(
                        f"INSERT INTO agents (id, {self._user_key_col}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
                        (agent_id, goal.user_api_key, agent_type, full_task[:2000], now),
                    )
                    conn.commit()
                finally:
                    conn.close()

            await self._execute_fn(agent_id, agent_type, full_task, goal.user_api_key, model=model)

            if self._get_db:
                conn = self._get_db()
                try:
                    row = conn.execute("SELECT result, status FROM agents WHERE id = ?", (agent_id,)).fetchone()
                finally:
                    conn.close()
                if row:
                    task.result = row[0] or ""
                    task.status = "completed" if row[1] == "completed" else "failed"

        except Exception as e:
            task.status = "failed"
            task.result = f"Error: {str(e)}"
            logger.error(f"Goal task {task.task_id} failed: {e}")

        task.completed_at = datetime.now(timezone.utc).isoformat()

    async def get_progress_report(self, goal_id: str, model: str = None) -> str:
        """Generate an executive progress report for a goal."""
        goal = self._goals.get(goal_id)
        if not goal:
            return "Goal not found"

        results = ""
        for proj in goal.projects:
            results += f"\n## {proj.title}\n"
            for task in proj.tasks:
                status_icon = "✅" if task.status == "completed" else "❌" if task.status == "failed" else "⏳"
                results += f"{status_icon} [{ROLES.get(task.role, {}).get('name', task.role)}] {task.title}: "
                results += (task.result[:300] if task.result else "No result") + "\n"

        if self._llm_call_fn:
            try:
                prompt = PROGRESS_REPORT_PROMPT.replace("{goal_title}", goal.title).replace("{goal_description}", goal.description).replace("{results}", results)
                return await self._llm_call_fn(prompt, "Generate the executive summary now.", model)
            except Exception:
                pass

        return f"Goal: {goal.title}\nStatus: {goal.status}\nProgress: {goal.to_dict()['progress']}%\n\n{results}"

    # ─── MANAGEMENT ──────────────────────────────────────

    def get_goal(self, goal_id: str) -> Optional[dict]:
        goal = self._goals.get(goal_id)
        return goal.to_dict() if goal else None

    def list_goals(self, user_api_key: str = None) -> list:
        goals = self._goals.values()
        if user_api_key:
            goals = [g for g in goals if g.user_api_key == user_api_key]
        return [g.to_dict() for g in goals]

    def pause_goal(self, goal_id: str) -> bool:
        goal = self._goals.get(goal_id)
        if goal:
            goal.status = "paused"
            return True
        return False

    def get_org_chart(self) -> list:
        return [{"role_id": rid, **{k: v for k, v in r.items() if k != "tools"}, "tool_count": len(r["tools"])} for rid, r in ROLES.items()]

    def get_role_detail(self, role_id: str) -> Optional[dict]:
        role = ROLES.get(role_id)
        if not role:
            return None
        return {
            "role_id": role_id, **role,
            "email_permissions": EMAIL_PERMISSIONS.get(role_id, {}),
        }

    def get_stats(self) -> dict:
        total_goals = len(self._goals)
        running = sum(1 for g in self._goals.values() if g.status == "running")
        completed = sum(1 for g in self._goals.values() if g.status == "completed")
        total_tasks = sum(sum(len(p.tasks) for p in g.projects) for g in self._goals.values())
        return {
            "total_goals": total_goals, "running": running, "completed": completed,
            "total_tasks": total_tasks, "available_roles": len(ROLES),
        }


# ─── COMPETITOR TRACKING PRESET ──────────────────────────

COMPETITOR_DAEMON_CONFIG = {
    "name": "Competitor Intelligence Tracker",
    "description": "Autonomously monitors competitor products weekly. Compares features, pricing, releases. Flags when you're behind.",
    "agent_type": "research",
    "interval_seconds": 604800,  # Weekly
    "task_description": """You are a competitive intelligence analyst. Your job is to monitor the AI agent platform market.

Track these competitors:
1. OpenClaw (openclaw.com) — open-source personal AI assistant
2. ZHC — autonomous company builder
3. Paperclip — zero-human company orchestration
4. Devin — AI software engineer
5. Cursor — AI code editor
6. Claude Code — Anthropic's coding agent

For each competitor, find:
- Latest release/update (version, date, features)
- New capabilities added
- Pricing changes
- Community growth (GitHub stars, users)
- Notable partnerships or funding

Then compare against APEX SWARM's capabilities:
- Where are we ahead?
- Where are we behind?
- What should we prioritize building next?

Output a structured competitive intelligence briefing with actionable recommendations.""",
    "alert_conditions": [
        {"field": "result", "operator": "contains", "value": "behind"},
        {"field": "result", "operator": "contains", "value": "gap"},
        {"field": "result", "operator": "contains", "value": "urgent"},
    ],
}
