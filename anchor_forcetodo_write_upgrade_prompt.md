# Prompt: Upgrade Anchor's main agent (planning loop, five whys, catalog-first, skills)

You are working in the codebase of **Anchor**, our in-house SRE AI agent. Implement the changes below in `anchor-main`. Read the existing code first, keep what works, and change only what this prompt asks for. Ask before deleting existing features.

**This is an upgrade, not a rewrite. Section 0 is mandatory and overrides anything below that would conflict with it.**

Two reference files accompany this prompt:
- `anchor_system_prompt.md`: the new system prompt (behavior rules, gate text, first eval case).
- `anchor_agent.py`: a working reference implementation of the graph described below. Adapt it to our codebase; don't paste it in blindly.

---

## 0. Do not break existing behavior

**Before changing anything**
1. Inventory what exists today and write it down in `docs/anchor-baseline.md`: graph nodes and edges, the current system prompt, every tool name exposed to the LLM, the UI/API/webhook request and response schemas, streaming or progress events the UI consumes, and what is written back to ServiceNow.
2. Build the eval harness (section 3.9) and run it against the **current** agent to record a baseline. Include at least: the Vault case, two or three past incidents, and two or three simple questions (e.g. "list pods in namespace X", "last deployment of service Y").

**While changing**
- **Feature flag.** Put the new flow behind `ANCHOR_AGENT_V2` (default off). With the flag off, the existing graph must run unchanged. Do not delete the old graph until V2 has passed evals and run in lower environments.
- **Keep contracts.** UI, API and webhook request/response schemas, streaming events and ServiceNow write-backs must keep working. If V2's answer format differs, keep the existing response fields and add new fields alongside them rather than renaming or removing.
- **Merge, don't replace, the system prompt.** Fold any rules, tool-usage notes or environment details from the current prompt into `anchor_system_prompt.md`. Flag anything you dropped and why.
- **Keep MCP tool names and arguments** exactly as they are. New local tools (`todo_write`, `catalog_lookup`, `fetch_skill`, `read_spilled_output`) must not collide with existing tool names; fail at startup if they do.
- **Simple questions behave as before.** The plan, nudge and review steps apply only to incidents/webhook intake or once a run has made 3+ data-gathering calls. A one-call question must never be nudged or reviewed.
- **One component per commit** (follow the build order in section 5) and re-run evals after each. Any regression against the baseline blocks the next step.
- **Fail soft.** Bad model output (invalid todo list), a broken prompt-file edit, a bad skill file, a catalog outage or a tool error must never crash a run. Return the error to the model or fall back to the last good version, and log it.

**Rollout:** lower environments with the flag on → compare eval results and real incidents against the old path → prod.

---

## 1. Context

**What Anchor is**
- `anchor-main` talks to the LLM (GPT-5.1 via OpenAI), built with **LangGraph**, and has a UI, APIs and a ServiceNow webhook.
- MCP servers (Python): `anchor-kube` (30+ K8s clusters, 20+ tools), `anchor-gitlab` (repos, CI/CD failures), `anchor-panorama` (Palo Alto firewalls across on-prem/Azure/AWS), `anchor-kibana`, `anchor-datadog`, `anchor-now` (ServiceNow incidents and change tasks).
- A **service catalog** service holds metadata for all microservices across the clusters (services, exposed hosts, namespaces, owners, dependencies), refreshed daily by a Python job.
- Environment: multi-tier network with a firewall-protected enclave, Istio service mesh, HashiCorp Vault secrets synced into on-prem K8s by an operator. Used for prod and lower environments.

**The problem**
Anchor works end to end but is less capable than intended. The same prompt with the same tools performs better in GitHub Copilot. Test failure: for a VaultStaticSecret whose target Secret is missing its `ownerReference`, Anchor stopped at "ownerRef is missing" instead of investigating why the operator failed to sync.

**Diagnosis**
The gap is in the agent loop and prompt layer, not the MCP servers. We compared Anchor against the open-source HolmesGPT agent and are adopting its strongest patterns: a forced planning loop, five-whys investigation rules, evidence discipline, large-output handling, a repeat-call guard, git-synced skills and an eval suite. Anchor keeps its own advantages (service catalog, firewall/enclave awareness, ServiceNow intake).

---

## 2. Target flow

```
intake → catalog resolve → plan (todo_write) → tool loop → gate/review → answer
                                   ↑______________________________|
```

1. **Intake:** take the incident or user prompt.
2. **Catalog resolve (code, not model-optional):** extract hints (service names, hosts, namespaces, error codes like 503/x509/OOMKilled/CrashLoopBackOff) and query the catalog before the first LLM call. Inject the result into the system prompt's `{{catalog_context}}` with a status:
   - single match → starting scope, verify against live data (catalog can be stale)
   - multiple matches → first task is to disambiguate
   - no match → retry with variations, then ask the user one specific question
   - catalog down → proceed and say so
   The intake path passes a `source` value (`chat`, `incident`, `webhook`, `api`) into the run; it controls whether a plan is enforced (3.4).
3. **Plan:** for incidents and multi-step investigations, the model must call `todo_write` before any other tool. Simple lookups answer directly, as today.
4. **Tool loop:** independent calls run in parallel; plan statuses update as work happens; every finding adds a "why did this happen?" task.
5. **Gate:** blocks the final answer until the plan is complete, then runs one review pass.
6. **Answer:** root cause, why-chain with evidence, impact, fix, other causes, not verified.

---

## 3. Components to build

### 3.1 State (LangGraph)
`messages`, `request`, `source`, `catalog_context`, `todos` (id, content, status pending/in_progress/completed, priority), `steps`, `tool_calls_made`, `gate_rounds`, `nudges`, `reviewed`, `gate_action`, `seen_calls`.

### 3.2 `todo_write` tool
- Takes the complete task list each call (replaces the previous one).
- Intercepted in the tool node to update state; returns the rendered plan.
- The current plan is re-rendered into the system prompt on every agent step.
- If any task is not completed after an update, reset `reviewed` to false.
- Validate the arguments; on invalid input return an error message to the model instead of raising.

### 3.3 Catalog
- A pre-call node that runs before the first LLM call (section 2, step 2).
- Also expose `catalog_lookup` as a tool so the model can retry and disambiguate.
- Wire it to our real catalog API (check its actual request/response shape).

### 3.4 Gate node and routing
- After the agent node: tool calls → tool node; no tool calls → gate; step limit hit with pending tool calls → finalize.
- Gate logic:
  - no plan and plan not required (source is `chat`/`api` and fewer than 3 data-gathering calls) → end, exactly like today
  - no plan (when required), or tasks still open, and nudges < 3 → inject the nudge message, loop back
  - a plan exists, all tasks complete, not yet reviewed, gate rounds < 2 → inject the review message, set `reviewed`, loop back
  - otherwise → end
- Finalize node: drop the dangling tool-call message and ask for the best answer from verified evidence, with hypotheses and unchecked items marked.
- Nudge and review message text: use the GATE PROMPT section of `anchor_system_prompt.md`.

### 3.5 Tool plumbing
- **Parallel execution** of all tool calls in one model turn, capped by a semaphore (`ANCHOR_MAX_PARALLEL_TOOLS`, default 6) so cluster APIs, Panorama and ServiceNow aren't flooded.
- **Repeat-call guard:** refuse an exact repeat (same tool + same args) within a run and tell the model to change parameters or move on. Tools that legitimately poll (e.g. re-checking status after a change) go in an exempt list (`ANCHOR_REPEAT_EXEMPT_TOOLS`).
- **Large output spill:** outputs over ~20k chars are written to a spill dir; the model receives a preview plus the path, and reads it back with a `read_spilled_output` tool (regex grep, offset/limit, restricted to the spill dir).
- **Spill location:** use a per-run subfolder on local disk, clean it up when the run ends, and never let `read_spilled_output` read outside it. Spilled files may contain sensitive data; don't put them anywhere shared.
- **Errors** from tools are returned to the model as evidence, not raised.

### 3.6 Skills (no-code updates)
- Skills live in a separate git repo: `<skill-name>/SKILL.md` with frontmatter `name` and `description`.
- Inject the skill catalog (name: description) into the prompt's `{{skill_catalog}}`.
- `fetch_skill(name)` tool returns the full skill. The model fetches only when a skill clearly matches.
- Background task runs `git pull --ff-only` every 5 minutes (configurable) and re-indexes; on failure, keep the last good index.
- Confirm the Anchor host can reach the skills repo (enclave/firewall rules, deploy key or token). If not, sync the folder by another route (sidecar, CI deploy) — the loader only needs the folder.
- Skip and log a skill file that fails to parse; never let one bad file empty the catalog.
- Skill names and descriptions must be symptom-specific (e.g. `vault-static-secret-not-syncing`).

### 3.7 No-code configuration
- **System prompt reload:** read `anchor_system_prompt.md` on each investigation, so prompt edits don't require a restart. Validate it at startup (fail fast), and at runtime fall back to the last good version if an edit breaks it.
- **Eval cases** in a YAML/JSON file, not in code: name, request, keywords the answer must mention, minimum plan size.
- Hard limits (max steps, gate rounds, nudges, spill threshold, skill pull interval) via environment variables.

### 3.8 Context compaction
Behind its own flag (`ANCHOR_COMPACTION`, default off) until evals show no loss. When the conversation approaches the model's context limit, summarize older messages with the LLM while keeping the original request, the catalog context, the current plan and the most recent tool results verbatim. Don't summarize individual tool outputs (it loses detail); spilling handles those.

### 3.9 Eval harness
- Command to run all eval cases and report PASS/FAIL, steps used, plan size and missing keywords.
- First case: the Vault ownerRef incident. Pass = reaches the operator-side cause with evidence for each link. Fail = stops at "ownerRef is missing".
- Add 4–5 more cases from past incidents before tuning further, plus the simple-question cases from section 0.
- Run every case on both paths (flag off and on) and report them side by side.
- Use lower-environment or recorded data for evals; the harness must never make changes to systems.

---

## 4. Behavior rules (already in `anchor_system_prompt.md`)

Use the prompt file as the system prompt. Key rules it enforces:
- **Five whys:** symptom → direct cause → deeper cause, until the cause is actionable or a stated limit is hit. If service A's problem traces to service B, investigate B.
- **Evidence:** every link backed by tool output, otherwise labeled a hypothesis with a task to verify it. Confirmed vs hypothesis kept separate. Error messages treated as exact evidence.
- **Blast radius:** name an entity as affected only with its own evidence; list "checked, healthy" and "not checked".
- **Multi-cluster:** label every finding with its real cluster and environment.
- **Environment knowledge:** enclave, firewalls, expired enclave certs (OpenSSL only from the enclave), NHID creds, JKS client certs in secrets, Istio 503 client/server split, Vault operator check order.

---

## 5. Build order

1. Baseline inventory, eval harness, Vault and simple-question cases; record results on the current agent.
2. State, `todo_write` and plan re-rendering.
3. Catalog pre-call node and `catalog_lookup` tool.
4. New system prompt with reload.
5. Gate node, routing and finalize.
6. Tool plumbing: parallel, repeat guard, spill.
7. Skills loader and git sync; write the first skill for Vault static secret sync failures.
8. Context compaction.
9. Re-run evals and compare with the baseline and with GitHub Copilot.
10. Roll out per section 0.

## 6. Out of scope for now
- Proactive detection of issues before they occur.
- Feedback-based RCA memory.
- UI redesign (keep the welcome page with prompt first, command center second).
- New integrations (ExtraHop, ESXi, F5, Venafi).

## 7. Acceptance criteria
- With `ANCHOR_AGENT_V2` off, Anchor behaves exactly as before (same tools, same responses, same UI/API/webhook/ServiceNow behavior).
- With it on, no baseline eval case gets worse; simple questions use no more steps than before.
- On incidents and multi-step investigations, the model calls `todo_write` before other tools.
- The agent cannot finish with open tasks (except via the step limit), and runs one review pass.
- Catalog context is present in the first LLM call.
- Repeated identical calls are refused; oversized outputs are spilled and readable.
- Pushing a new `SKILL.md` makes it available within the pull interval without a restart; editing the prompt file takes effect on the next investigation.
- The Vault eval case passes.
- Invalid todo input, a broken prompt edit, a bad skill file and a catalog outage each leave the run working, with an error logged.
