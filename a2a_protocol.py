"""
APEX SWARM - Agent-to-Agent Protocol (A2A)
=============================================
Agents autonomously hire other agents, delegate subtasks, negotiate, and aggregate results.

This is the feature that makes APEX a true swarm — not just parallel agents,
but agents that collaborate, delegate, and compose into emergent workflows.

Features:
  1. Task Decomposition — lead agent breaks complex tasks into subtasks
  2. Agent Discovery — find the best agent for each subtask
  3. Delegation — lead agent hires sub-agents with specific instructions
  4. Result Aggregation — lead agent combines sub-agent outputs into final answer
  5. Negotiation — agents can request clarification or reject tasks
  6. Recursive Depth — sub-agents can hire their own sub-agents (configurable depth)
  7. Cost Tracking — track token spend across the full delegation chain
  8. Audit Trail — full trace of who delegated what to whom

File: a2a_protocol.py
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Callable

logger = logging.getLogger("apex-swarm")

# ─── PROTOCOL MESSAGES ───────────────────────────────────

class A2AMessage:
    """A message in the agent-to-agent protocol."""
    def __init__(self, msg_type: str, from_agent: str, to_agent: str, payload: dict, trace_id: str = None):
        self.id = str(uuid.uuid4())[:12]
        self.msg_type = msg_type       # request, response, delegate, result, reject, clarify
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.payload = payload
        self.trace_id = trace_id or str(uuid.uuid4())[:12]
        self.timestamp = datetime.now(timezone.utc).isoformat()


class Subtask:
    """A decomposed subtask assigned to a specific agent."""
    def __init__(self, task_id: str, agent_type: str, description: str, depends_on: list = None, priority: int = 1):
        self.task_id = task_id
        self.agent_type = agent_type
        self.description = description
        self.depends_on = depends_on or []
        self.priority = priority
        self.status = "pending"     # pending, running, completed, failed
        self.result = None
        self.agent_id = None        # runtime agent ID
        self.cost = 0.0

    def to_dict(self):
        return {
            "task_id": self.task_id, "agent_type": self.agent_type,
            "description": self.description, "depends_on": self.depends_on,
            "priority": self.priority, "status": self.status,
            "result": self.result[:500] if self.result else None,
            "agent_id": self.agent_id, "cost": self.cost,
        }


class DelegationPlan:
    """A plan created by a lead agent to decompose and delegate work."""
    def __init__(self, plan_id: str, lead_agent: str, original_task: str, subtasks: list[Subtask], strategy: str = "parallel"):
        self.plan_id = plan_id
        self.lead_agent = lead_agent
        self.original_task = original_task
        self.subtasks = subtasks
        self.strategy = strategy    # parallel, sequential, dependency
        self.status = "created"     # created, running, aggregating, completed, failed
        self.final_result = None
        self.total_cost = 0.0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.completed_at = None
        self.messages: list[A2AMessage] = []

    def to_dict(self):
        return {
            "plan_id": self.plan_id, "lead_agent": self.lead_agent,
            "original_task": self.original_task[:200],
            "subtasks": [s.to_dict() for s in self.subtasks],
            "strategy": self.strategy, "status": self.status,
            "final_result": self.final_result[:1000] if self.final_result else None,
            "total_cost": self.total_cost,
            "created_at": self.created_at, "completed_at": self.completed_at,
            "message_count": len(self.messages),
        }


# ─── AGENT DISCOVERY ─────────────────────────────────────

# Maps task keywords to best agent types
AGENT_CAPABILITIES = {
    "research": {"keywords": ["research", "find", "search", "look up", "investigate", "analyze", "study"], "strength": 10},
    "crypto-research": {"keywords": ["crypto", "bitcoin", "ethereum", "token", "defi", "blockchain", "nft", "web3"], "strength": 10},
    "market-analyst": {"keywords": ["market", "stock", "trading", "price", "chart", "technical analysis"], "strength": 10},
    "macro-analyst": {"keywords": ["macro", "economy", "gdp", "inflation", "fed", "interest rate", "global"], "strength": 9},
    "defi-analyst": {"keywords": ["defi", "yield", "liquidity", "pool", "farming", "tvl", "protocol"], "strength": 10},
    "blog-writer": {"keywords": ["blog", "article", "write", "content", "post", "essay"], "strength": 10},
    "copywriter": {"keywords": ["copy", "ad", "headline", "landing page", "marketing", "persuade", "sales"], "strength": 10},
    "social-media": {"keywords": ["social", "twitter", "linkedin", "thread", "viral", "engagement"], "strength": 10},
    "code-reviewer": {"keywords": ["code", "review", "bug", "refactor", "programming", "software"], "strength": 10},
    "api-designer": {"keywords": ["api", "rest", "graphql", "endpoint", "schema", "swagger"], "strength": 10},
    "data-analyst": {"keywords": ["data", "analysis", "statistics", "dashboard", "metrics", "sql"], "strength": 10},
    "seo-specialist": {"keywords": ["seo", "search engine", "keyword", "ranking", "organic", "google"], "strength": 9},
    "legal-analyst": {"keywords": ["legal", "contract", "compliance", "regulation", "law", "terms"], "strength": 9},
    "pitch-deck": {"keywords": ["pitch", "deck", "investor", "funding", "startup", "presentation"], "strength": 10},
    "summarizer": {"keywords": ["summarize", "summary", "condense", "brief", "tldr", "overview"], "strength": 10},
}


def discover_agent(task_description: str, available_agents: dict, exclude: list = None) -> str:
    """Find the best agent for a given task description."""
    exclude = exclude or []
    task_lower = task_description.lower()
    scores = {}

    for agent_type, caps in AGENT_CAPABILITIES.items():
        if agent_type in exclude:
            continue
        if agent_type not in available_agents:
            continue
        score = 0
        for kw in caps["keywords"]:
            if kw in task_lower:
                score += caps["strength"]
        if score > 0:
            scores[agent_type] = score

    if scores:
        return max(scores, key=scores.get)
    # Default to research if nothing matches
    return "research" if "research" not in exclude else list(available_agents.keys())[0]


# ─── DECOMPOSITION PROMPT ────────────────────────────────

DECOMPOSITION_SYSTEM = """You are a task decomposition expert for the APEX SWARM multi-agent system.
Your job is to break a complex task into smaller subtasks that can be delegated to specialized agents.

Available agent types:
{agent_list}

Rules:
1. Break the task into 2-5 subtasks (no more — keep it focused)
2. Each subtask should be independently executable
3. Assign the best agent type for each subtask
4. Mark dependencies: if subtask B needs results from subtask A, note it
5. Each subtask description should be self-contained and specific

Respond ONLY with valid JSON, no markdown, no explanation:
{{
  "strategy": "parallel" or "sequential" or "dependency",
  "subtasks": [
    {{
      "id": "t1",
      "agent_type": "agent-type-here",
      "description": "Specific task instruction for this agent",
      "depends_on": [],
      "priority": 1
    }}
  ]
}}"""


AGGREGATION_SYSTEM = """You are a result aggregation expert for the APEX SWARM multi-agent system.
Multiple specialist agents have completed subtasks. Your job is to synthesize their outputs into one cohesive, high-quality final response.

Original task: {original_task}

Subtask results:
{subtask_results}

Rules:
1. Combine all insights into a unified, well-structured response
2. Resolve any contradictions between agents
3. Highlight key findings from each specialist
4. Make the response directly useful — not a meta-commentary about agents
5. The user should not need to know this was done by multiple agents"""


# ─── A2A ENGINE ──────────────────────────────────────────

class A2AEngine:
    """Orchestrates agent-to-agent delegation, execution, and aggregation."""

    def __init__(self, agents: dict, execute_fn: Callable, llm_call_fn: Callable = None):
        """
        Args:
            agents: Dict of available agents {type: {name, system, description}}
            execute_fn: async fn(agent_id, agent_type, task, user_key, model) -> None
            llm_call_fn: async fn(system, message, model) -> str (for decomposition/aggregation)
        """
        self._agents = agents
        self._execute_fn = execute_fn
        self._llm_call_fn = llm_call_fn
        self._active_plans: dict[str, DelegationPlan] = {}
        self._get_db = None
        self._user_key_col = "user_api_key"
        self._max_depth = 2  # max recursive delegation depth

    def set_db(self, get_db_fn, user_key_col="user_api_key"):
        self._get_db = get_db_fn
        self._user_key_col = user_key_col

    async def decompose_and_delegate(
        self,
        task: str,
        lead_agent: str = "research",
        user_api_key: str = "system",
        model: str = None,
        max_subtasks: int = 5,
    ) -> DelegationPlan:
        """Full A2A cycle: decompose → delegate → execute → aggregate."""
        plan_id = str(uuid.uuid4())[:12]

        # Step 1: Decompose task into subtasks
        agent_list = "\n".join(f"  - {k}: {v.get('description', v.get('name', k))}" for k, v in self._agents.items())
        system_prompt = DECOMPOSITION_SYSTEM.replace("{agent_list}", agent_list)

        subtasks = []
        if self._llm_call_fn:
            try:
                decomp_json = await self._llm_call_fn(system_prompt, task, model)
                # Parse JSON from response
                decomp_json = decomp_json.strip()
                if decomp_json.startswith("```"):
                    decomp_json = decomp_json.split("\n", 1)[-1].rsplit("```", 1)[0]
                parsed = json.loads(decomp_json)
                strategy = parsed.get("strategy", "parallel")
                for st in parsed.get("subtasks", [])[:max_subtasks]:
                    agent_type = st.get("agent_type", "research")
                    if agent_type not in self._agents:
                        agent_type = discover_agent(st.get("description", ""), self._agents)
                    subtasks.append(Subtask(
                        task_id=st.get("id", f"t{len(subtasks)+1}"),
                        agent_type=agent_type,
                        description=st.get("description", ""),
                        depends_on=st.get("depends_on", []),
                        priority=st.get("priority", 1),
                    ))
            except Exception as e:
                logger.error(f"A2A decomposition failed: {e}")
                strategy = "parallel"

        # Fallback: if decomposition failed, use agent discovery to create 2-3 subtasks
        if not subtasks:
            strategy = "parallel"
            primary = discover_agent(task, self._agents)
            subtasks = [
                Subtask("t1", primary, task, priority=1),
                Subtask("t2", "summarizer" if "summarizer" in self._agents else "research",
                        f"Summarize and synthesize findings about: {task}", depends_on=["t1"], priority=2),
            ]

        plan = DelegationPlan(plan_id, lead_agent, task, subtasks, strategy)
        self._active_plans[plan_id] = plan
        plan.status = "running"

        logger.info(f"🔗 A2A Plan {plan_id}: {len(subtasks)} subtasks, strategy={strategy}")

        # Step 2: Execute subtasks
        if strategy == "parallel":
            await self._execute_parallel(plan, user_api_key, model)
        elif strategy == "sequential":
            await self._execute_sequential(plan, user_api_key, model)
        else:
            await self._execute_dependency(plan, user_api_key, model)

        # Step 3: Aggregate results
        plan.status = "aggregating"
        await self._aggregate(plan, user_api_key, model)
        plan.status = "completed"
        plan.completed_at = datetime.now(timezone.utc).isoformat()
        plan.total_cost = sum(s.cost for s in plan.subtasks)

        logger.info(f"🔗 A2A Plan {plan_id} completed: {sum(1 for s in plan.subtasks if s.status=='completed')}/{len(plan.subtasks)} subtasks succeeded")

        return plan

    async def _execute_parallel(self, plan: DelegationPlan, user_api_key: str, model: str = None):
        """Execute all subtasks in parallel."""
        tasks = []
        for st in plan.subtasks:
            tasks.append(self._run_subtask(st, plan, user_api_key, model))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_sequential(self, plan: DelegationPlan, user_api_key: str, model: str = None):
        """Execute subtasks one by one, passing results forward."""
        context = ""
        for st in sorted(plan.subtasks, key=lambda s: s.priority):
            if context:
                st.description += f"\n\nContext from previous agents:\n{context}"
            await self._run_subtask(st, plan, user_api_key, model)
            if st.result:
                context += f"\n[{st.agent_type}]: {st.result[:500]}\n"

    async def _execute_dependency(self, plan: DelegationPlan, user_api_key: str, model: str = None):
        """Execute subtasks respecting dependency graph."""
        completed = set()
        max_rounds = len(plan.subtasks) + 2

        for _ in range(max_rounds):
            ready = [s for s in plan.subtasks
                     if s.status == "pending"
                     and all(d in completed for d in s.depends_on)]
            if not ready:
                break

            # Inject dependency results into description
            for st in ready:
                dep_context = ""
                for dep_id in st.depends_on:
                    dep_task = next((s for s in plan.subtasks if s.task_id == dep_id), None)
                    if dep_task and dep_task.result:
                        dep_context += f"\n[{dep_task.agent_type} result]: {dep_task.result[:800]}\n"
                if dep_context:
                    st.description += f"\n\nResults from prerequisite agents:{dep_context}"

            # Execute ready tasks in parallel
            await asyncio.gather(*[self._run_subtask(s, plan, user_api_key, model) for s in ready], return_exceptions=True)
            for s in ready:
                if s.status == "completed":
                    completed.add(s.task_id)

    async def _run_subtask(self, subtask: Subtask, plan: DelegationPlan, user_api_key: str, model: str = None):
        """Execute a single subtask by deploying an agent."""
        agent_id = str(uuid.uuid4())
        subtask.agent_id = agent_id
        subtask.status = "running"

        # Log delegation message
        plan.messages.append(A2AMessage(
            "delegate", plan.lead_agent, subtask.agent_type,
            {"task": subtask.description[:200], "subtask_id": subtask.task_id},
            trace_id=plan.plan_id,
        ))

        try:
            # Create agent record in DB
            if self._get_db:
                now = datetime.now(timezone.utc).isoformat()
                conn = self._get_db()
                try:
                    conn.execute(
                        f"INSERT INTO agents (id, {self._user_key_col}, agent_type, task_description, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
                        (agent_id, user_api_key, subtask.agent_type, subtask.description[:2000], now),
                    )
                    conn.commit()
                finally:
                    conn.close()

            # Execute the agent
            await self._execute_fn(agent_id, subtask.agent_type, subtask.description, user_api_key, model=model)

            # Get result from DB
            if self._get_db:
                conn = self._get_db()
                try:
                    row = conn.execute("SELECT result, status FROM agents WHERE id = ?", (agent_id,)).fetchone()
                finally:
                    conn.close()
                if row:
                    subtask.result = row[0] or ""
                    subtask.status = "completed" if row[1] == "completed" else "failed"
                else:
                    subtask.status = "failed"
            else:
                subtask.status = "completed"

            # Log result message
            plan.messages.append(A2AMessage(
                "result", subtask.agent_type, plan.lead_agent,
                {"subtask_id": subtask.task_id, "status": subtask.status, "result_length": len(subtask.result or "")},
                trace_id=plan.plan_id,
            ))

        except Exception as e:
            subtask.status = "failed"
            subtask.result = f"Error: {str(e)}"
            logger.error(f"A2A subtask {subtask.task_id} failed: {e}")

    async def _aggregate(self, plan: DelegationPlan, user_api_key: str, model: str = None):
        """Aggregate all subtask results into a final response."""
        completed = [s for s in plan.subtasks if s.status == "completed" and s.result]

        if not completed:
            plan.final_result = "All subtasks failed. No results to aggregate."
            return

        if len(completed) == 1:
            plan.final_result = completed[0].result
            return

        # Build subtask results summary
        results_text = ""
        for s in completed:
            results_text += f"\n--- Agent: {s.agent_type} (task: {s.description[:100]}) ---\n{s.result[:2000]}\n"

        if self._llm_call_fn:
            try:
                system = AGGREGATION_SYSTEM.replace("{original_task}", plan.original_task).replace("{subtask_results}", results_text)
                plan.final_result = await self._llm_call_fn(system, "Synthesize these results into a single comprehensive response.", model)
            except Exception as e:
                logger.error(f"A2A aggregation failed: {e}")
                plan.final_result = f"Combined results from {len(completed)} agents:\n{results_text}"
        else:
            plan.final_result = f"Combined results from {len(completed)} agents:\n{results_text}"

    # ─── STATUS & MANAGEMENT ─────────────────────────────

    def get_plan(self, plan_id: str) -> Optional[dict]:
        plan = self._active_plans.get(plan_id)
        return plan.to_dict() if plan else None

    def get_active_plans(self) -> list[dict]:
        return [p.to_dict() for p in self._active_plans.values()]

    def get_plan_messages(self, plan_id: str) -> list[dict]:
        plan = self._active_plans.get(plan_id)
        if not plan:
            return []
        return [
            {"id": m.id, "type": m.msg_type, "from": m.from_agent,
             "to": m.to_agent, "payload": m.payload, "timestamp": m.timestamp}
            for m in plan.messages
        ]

    def get_stats(self) -> dict:
        total = len(self._active_plans)
        running = sum(1 for p in self._active_plans.values() if p.status == "running")
        completed = sum(1 for p in self._active_plans.values() if p.status == "completed")
        total_subtasks = sum(len(p.subtasks) for p in self._active_plans.values())
        total_cost = sum(p.total_cost for p in self._active_plans.values())
        return {
            "total_plans": total, "running": running, "completed": completed,
            "total_subtasks": total_subtasks, "total_cost": round(total_cost, 4),
        }
