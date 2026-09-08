# Engineering candidate take-home brief

---

### Context

Rubi brings all the context relevant to a deal — documents, meetings, and emails — into one place so PE firms can build agents to automate their work.

Our agent platform is where the work gets done. We've built a modular harness where users configure agents to carry out specific tasks: screening deal documents, scanning the internet for potential new deals, proactively nurturing relationships with bankers and brokers. Every agent is composed from the same primitives, and every one of them is customizable:

1. **Trigger:** what starts an agent session — a scheduled cron job, a manual prompt, or a specific in-app event.
2. **Model:** self explanatory. Rubi is multi-model, so users pick the best model for the task.
3. **Instructions:** the system prompt that gives the model the agent's goal, the steps to reach it, and what success looks like.
4. **Skills:** folders of instructions and scripts that add context and procedure relevant to the agent's goal.
5. **Tools:** Rubi-native tools plus tools from external MCPs, giving the agent the ability to act in Rubi and in other systems.
6. **Memory:** persistent, cross-session context the model stores on a per-agent basis.

We design our agents to behave like ambitious associates: autonomous and self-sufficient, but aware of their limits and of when to ask for help. Every agent carries a generic `request_input` tool. When an agent uses it, the run pauses and a human is brought into the loop to approve an action or make a call.

### Problem

Agents request input exactly when human judgement is most valuable: a final go/no-go on a potential deal, a tone check on an email to a critical banker relationship, a clarification of the thesis before a search starts. In theory, these responses are a gold mine of structured human feedback. In practice, we keep the raw response only as part of the run record, and nothing ever reads it again. The next run of the same agent, or of a sibling agent working the same deal, asks the same question from scratch. Nothing adjusts the agent's judgement, its context, or its lens based on what a human already told it.

### Challenge

Design and build the MVP of a self-learning loop for our harness, using human responses to `request_input` as the primary input. The loop needs to store responses in a structured form and feed them agentically into something an agent can already read today: memory, skills, or the agent's system prompt. Key things to think about:

- Our agent builder is modular and can support effectively infinite use cases, so agents ask for input for all sorts of reasons. The loop must be agent and use-case agnostic. Deal decisions are the worked example, not the spec.
- Where in the harness should the feedback land: memory, a skill, the instructions, something new? Each has a different reach and a different blast radius.
- How do you tell feedback that belongs to one agent from feedback that should be shared harness-wide, and what mechanism holds each? Think about scope as well: is an answer about this user, this firm, this agent, or this deal?
- Not every ask deserves to be learned from. Some are a data-model gap a human is patching, some are a runtime failure routed to a person, some are a real judgement call. Decide which the loop should absorb and which it should refuse.
- How does the agent self-update? Fully autonomous, proposes a change for a human to accept, or something in between? What gets versioned, and who can undo it?
- How would you know it's working? A loop with no measure of its own effect is just drift.

### How you'll complete this

We've built an isolated sandbox repo: a lightweight duplicate of our agent harness and its key facets, on public dependencies only. You'll get a private GitHub repo, a README, and an API key on our account.

**What's in the sandbox**

- **The harness.** A tool registry, composable skills, memory and preference stores, versioned agent definitions, and a middleware stack that sits between the model and the world: tool auth, an approval gate, error recovery, tracing, and an empty slot labelled guards.
- `request_input`**, behaving like ours.** Choose-style and approve-style asks, batching of several questions into one pause, a safe default and a TTL. The pause works the way production works: a pending-input row is written, the run stops, and resuming is a fresh invocation carrying the human's answers. It is deliberately not the in-graph interrupt a framework gives you for free.
- **Three seeded agents** at two fictional firms: a CIM screener that fires every ask shape we see in production, a teaser-intake agent that works the same deals, and a CRM-hygiene agent that runs unattended at night. Each has instructions, skills, tools, and per-tool gate modes you can edit.
- **Four scenarios** you can run from the CLI, and a replay harness that runs a scenario several times and asserts on what happened. It ships with one assertion already failing: on day two, both agents re-ask a question a human answered on day one. That failing check is your starting line.
- **A real model** on our key, plus a scripted fake model so the replay harness is deterministic and free.

**What's deliberately missing**

The README lists it in full. The short version: nothing reads a pending input after its run, memory never sees tool messages, the stored "rationale" is the model's and not the human's, there is no place for a human to say why, and the guards slot is empty. Some of that is the problem; some of it is a hint.

**Getting started**

1. Clone, `uv sync`, copy `.env.example` and drop in the key.
2. Run `day1_screen`, answer the two cards, watch the run complete.
3. Run `day2_repeat` and the replay harness. Read the trace.
4. Then start designing. The README has a map of every lever in the harness and the file that owns it.

### Challenge requirements

<aside>
⏱️

Spend no more than 10 hours on this, and it's fine if it's incomplete. We would much rather see where you left off, with a short note on what you would have done with more time, than a polished version that took twenty hours.

</aside>

1. **A planning artifact**, in whatever format and medium you normally use to think about design before building. We want to see the shape of your reasoning: the options you considered, where the loop lands and why, what you decided not to build, and how you'd measure the effect. A page of prose, a diagram, a doc with a table, whatever is honest to how you work.
2. **A working MVP of the loop.** Responses stored in the backend in a structured form and fed to the model through whichever part of the harness you chose. The target: after your change, the replay harness's failing check passes, and you can show in the trace why. If you don't get there in the time, show us how far you got and what the next steps would have been. An honest half with a clear plan for the rest is a good submission.
3. **A presentation of both**, to the product and engineering team. Plan for roughly 45 minutes: 15 to 20 minutes walking us through the design and a live run of the sandbox, then discussion.

### How we'll be assessing you

**Problem solving and feature design** (most important). Did you frame the problem before solving it? A strong answer separates the kinds of ask before deciding what to learn from, names where the loop closes and why the alternatives lose, and says how it would know the loop is helping. We care more about a small mechanism placed correctly than a large one placed by default.

**Comfort with harnesses and building agents.** Can you reason about the boundary between what the model sees and what the runtime enforces? A rule that reaches the model is prose; a rule that reaches middleware is a guard. Do you know which you're building, and did you consider the failure modes, such as a learned answer quietly skipping a gate that was there for a reason?

**Code execution, and how you use AI to get there.** We expect you to use AI tools heavily, and we'll look at how. Does the code reflect a design you own, or a design the tool picked? Is it small, readable, and honest about what it doesn't handle? We'd rather see a narrow change that works end to end than a broad one that half works.

**Presenting and defending an approach.** Can you explain the decision to people who know the system better than you, hold the parts you're confident in, and concede the parts you aren't? Changing your mind in the room on good evidence counts for you, not against you.
