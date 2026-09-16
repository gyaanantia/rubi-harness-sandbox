import asyncio
import os
from copy import deepcopy

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import tracing_context

from harness import learning, prompt, registry
from harness.middleware import build_middleware
from harness.middleware.approval_gate import GateAwaitingApproval
from harness.middleware.trace import record
from harness.store.definitions import DefinitionStore
from harness.store.feedback import FeedbackStore
from harness.store.memory import MemoryStore
from harness.store.pending_inputs import DEFAULT_TTL, PendingInputStore
from harness.store.preferences import PreferenceStore
from harness.store.proposals import ProposalStore
from harness.store.runs import Run, RunStore
from harness.store.skills import SkillStore


def build_agent(definition, ctx):
    tools = [registry.get(name) for name in dict.fromkeys([*definition.tools, "request_input"])]
    return create_agent(
        ctx["model"],
        tools,
        system_prompt=prompt.compose(definition, ctx),
        middleware=build_middleware(ctx),
        checkpointer=ctx["checkpointer"],
        context_schema=dict,
    )


def real_model():
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("SANDBOX_MODEL"):
        raise ValueError("Set OPENAI_API_KEY and SANDBOX_MODEL in .env, or use --fake")
    return ChatOpenAI(
        model=os.environ["SANDBOX_MODEL"],
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://api.openai.com/v1",
        max_tokens=4096,
        max_retries=0,
        timeout=60,
    )


class Runtime:
    def __init__(self, gateway, *, fake=False, ttl=DEFAULT_TTL):
        self.gateway = gateway
        self.fake = fake
        self.ttl = ttl
        self.runs = RunStore()
        self.pending_inputs = PendingInputStore()
        self.definitions = DefinitionStore()
        self.skills = SkillStore()
        self.memory = MemoryStore()
        self.preferences = PreferenceStore()
        self.feedback = FeedbackStore()
        self.proposals = ProposalStore()
        self.checkpointer = InMemorySaver()
        self.contexts = {}
        self.graphs = {}
        self.locks = {}

    async def run(self, definition, kickoff, bindings, user=None, *, model=None):
        from seed.firms import FIRMS

        if user is not None and user not in FIRMS[definition.firm_id]["users"]:
            raise ValueError("User is outside this firm")
        run = Run(
            definition.agent_id,
            definition.version,
            definition.firm_id,
            user,
            deepcopy(bindings),
            kickoff,
        )
        self.runs.rows[run.id] = run
        self.locks[run.id] = asyncio.Lock()
        if model is None:
            from harness.fake_model import ScriptedModel

            model = ScriptedModel() if self.fake else real_model()
        ctx = {
            "run": run,
            "definition": deepcopy(definition),
            "model": model,
            "gateway": self.gateway,
            "pending_inputs": self.pending_inputs,
            "memory": self.memory,
            "preferences": self.preferences,
            "feedback": self.feedback,
            "proposals": self.proposals,
            "skills": self.skills,
            "checkpointer": self.checkpointer,
            "ttl": self.ttl,
            "receipts": {},
            "failures": {},
            "gate_decisions": {},
        }
        self.contexts[run.id] = ctx
        self.graphs[run.id] = build_agent(definition, ctx)
        return await self._invoke(run, [HumanMessage(kickoff)])

    async def _invoke(self, run, messages):
        ctx = self.contexts[run.id]
        try:
            # Suppress tracing even when a parent shell has enabled it globally.
            with tracing_context(enabled=False):
                result = await self.graphs[run.id].ainvoke(
                    {"messages": messages},
                    config={"configurable": {"thread_id": run.thread_id}, "recursion_limit": 60},
                    context=ctx,
                )
        except GateAwaitingApproval:
            return {"run_id": run.id, "paused": True, "pending": self.pending(run.id)}
        except Exception as error:
            run.status = "failed"
            record(ctx, "run", status="failed", error=type(error).__name__)
            return {"run_id": run.id, "paused": False, "error": str(error)}
        run.status = "completed"
        learning.absorb(ctx)
        return {"run_id": run.id, "paused": False, "output": result["messages"][-1].text}

    def pending(self, run_id):
        return [row for row in self.pending_inputs.for_run(run_id) if row.status == "pending"]

    async def resume(self, run_id, *, firm_id):
        run = self.runs.get(run_id, firm_id)
        async with self.locks[run_id]:
            if run.status not in {"paused_input", "paused_approval"}:
                raise ValueError(f"Cannot resume a {run.status} run")
            if self.pending(run_id):
                return {"run_id": run_id, "paused": True, "pending": self.pending(run_id)}
            rows = self.pending_inputs.for_run(run_id)
            if any(row.status == "expired" or row.response is None for row in rows):
                raise ValueError("Run has expired or unanswered inputs")
            self.contexts[run_id]["gate_decisions"] = {
                row.tool_call_id: deepcopy(row.response) for row in rows
            }
            run.status = "running"
            return await self._invoke(run, [])
