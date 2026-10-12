# Task: Upgrade the Anchor main agent so it investigates like a senior SRE

## Context
Anchor (`anchor-main`) is our SRE AI agent. It uses GPT-5.1 with LangGraph and drives these MCP servers: `anchor-kube` (30 K8s clusters), `anchor-gitlab`, `anchor-panorama`, `anchor-kibana`, `anchor-datadog`, `anchor-now` (ServiceNow), plus a service catalog service (metadata for all microservices, refreshed daily).

**Problem:** The same prompt with the same tools works noticeably better in GitHub Copilot than in Anchor. Anchor stops early, picks weak tool arguments, and fails to locate the server side of an issue (for example an Istio 503) when the report is vague.

**Goal:** Make Anchor investigate autonomously and persistently, with hypothesis-driven reasoning, and produce an evidence-backed RCA. Do not break the existing MCP servers or the UI/API/webhook interfaces.

## First: inspect before changing
1. Read the current agent code: graph definition, system prompt, how tools are bound, how the LLM is called, step limits, how tool output is passed back.
2. Write a short `docs/current-state.md` listing what you found against the requirements below (what exists, what's missing). Then implement.

## Requirements

### 1. Agent loop: autonomous, not rigid
- The investigation node must be a ReAct-style tool-calling loop: the model decides which tool to call next, observes the result, and continues until it has an evidence-backed conclusion or hits the step limit.
- Do not hard-code a fixed sequence of tool calls. LangGraph handles the outer flow only: intake -> entity resolution -> investigate -> RCA -> feedback.
- Config via env or settings file: `MAX_STEPS` (default 80; HolmesGPT defaults to 100), `REASONING_EFFORT` (default `medium`; `high` for prod incidents), `MODEL`.
- When the step limit is hit, return what was found, what was ruled out, and what remains unchecked. Never fail silently.

### 1a. Planning tool (TodoWrite-style) with phases and gates
This is the main mechanism that keeps the agent persistent. Implement it as a tool the model must use.
- Add a `todo_write(tasks)` tool. Each task has `id`, `content`, `status` (`pending` | `in_progress` | `completed` | `failed`). The tool stores the list in agent state and returns the formatted list to the model on every call.
- For any multi-step investigation the model MUST call `todo_write` first to create its plan (phase 1), then update statuses as it works. Batch status updates into one call, and issue independent tool calls in parallel with it.
- Serialize only tasks that depend on earlier results (for example: find pod name, then get its logs).
- After every tool result, append a short system reminder to the next model input: "Update your task list. Are all tasks completed?"
- **Phase gate:** when all tasks in the current phase are completed, the model must STOP and evaluate: (a) Can I completely answer the question? (b) Have I reached the actual root cause (keep asking "why" up to five times)? (c) Did the investigation surface new areas to explore (upstream/downstream service, firewall, certificate, credentials, recent change)? If any answer is no, it must call `todo_write` to create the next phase.
- **Clarification gate:** if entity resolution (section 3) is still ambiguous after catalog lookup and a first round of tool checks, ask the user one concise question. Otherwise do not ask.

### 1b. Final review gate
Before the model may produce the RCA, it must run a final review task and confirm:
- All tasks show `completed` (or `failed` with a reason).
- Every claim in the RCA is traced to a specific tool output (tool name, timestamp, identifier).
- Anything unverified is hedged ("possible cause", "unconfirmed") and listed under "Not checked".
- Resource names, namespaces, clusters and hosts are exact and any suggested commands are complete and runnable for this environment.
Enforce in code: reject the final answer if the task list has open tasks, and send the model back to finish or mark them failed.

### 2. Use the OpenAI Responses API and preserve reasoning
- Switch the LLM calls to the Responses API if we are on Chat Completions.
- Pass reasoning items back to the model across tool-call turns (use `previous_response_id` or re-send reasoning items).
- Set reasoning effort from config.

### 3. Entity resolution pre-step (before the LLM investigates)
- Input: the user prompt or incident text (ServiceNow webhook, UI, or API).
- Extract candidate service names, hostnames, URLs, error codes, cluster or namespace hints.
- Call the service catalog service to resolve them to: service, cluster(s), namespace, exposed hosts, upstream and downstream dependencies, owning team.
- Inject the resolved context into the investigation prompt as a structured block. If resolution is ambiguous, include the top candidates and tell the model to confirm with tools.
- Only the catalog lookup is deterministic. The LLM still chooses all investigation tools.

### 4. Skills (playbooks) as files, loaded on demand
- Create `skills/` with one markdown file per playbook. Frontmatter: `name`, `description` (when to use), `tags`.
- Add two tools to the agent: `list_skills()` returning names and descriptions, and `load_skill(name)` returning the content.
- The system prompt tells the model to call `list_skills` at the start of an investigation and load any relevant skills, but skills are guidance, not limits.
- Skills must be updatable by editing and pushing files, with no code change.
- Create initial skills: `istio-503`, `expired-cert-enclave`, `firewall-access-block`, `bad-client-cert-jks`, `bad-nhid-credentials`, `pod-crashloop-oom`, `deployment-rollout-failure`. Use the template below.

### 5. General investigation method (always in the system prompt, independent of skills)
This is the fallback when no skill matches. See the system prompt draft below.

### 6. Tool output shaping
- Truncate or summarize large tool outputs (logs, pod lists, YAML) before they reach the model, keeping errors, timestamps and identifiers. Always say how much was cut and how to fetch more.
- Make tool errors actionable (for example "namespace not found; closest matches: X, Y").
- Review each MCP tool description: it must say when to use it and when not to, with parameter examples.
- **Per-server instructions:** each MCP server gets a short instructions file (`instructions/anchor-kube.md`, `anchor-panorama.md`, `anchor-kibana.md`, `anchor-datadog.md`, `anchor-gitlab.md`, `anchor-now.md`) that is merged into the system prompt when that server is enabled. Examples: kube = summarize large outputs, check pod state before logs, check both client and server cluster; panorama = look up the matching rule and zone before concluding a block; kibana = narrow by time window and service first.
- **Context budget:** cap each tool result at a configurable percentage of the context window (`TOOL_MAX_CONTEXT_PCT`, default 20%). For logs, keep the most recent entries and any error lines. When context grows large, compact older tool results into summaries while keeping the task list and key evidence intact.

### 7. Tracing and observability
- Log every step as JSONL: step number, model reasoning summary, tool name, arguments, truncated result, latency, tokens.
- Add a trace viewer or at minimum a `scripts/replay_trace.py` so we can compare Anchor's run against Copilot's run for the same prompt.

### 8. Evaluation harness
- Create `evals/cases/*.json`, each with: `input` (vague developer-style report), `expected_root_cause`, `expected_evidence` (tools or data that should have been consulted), `max_steps`.
- Create `scripts/run_evals.py` that runs all cases, saves traces, and scores each: root cause correct (LLM-judge against expected), key evidence found, steps used, tokens used.
- Seed it with 5 placeholder cases from our past incidents (I will fill in real ones).

### 9. Coverage-gap logging (learning loop)
- When an investigation ends with no matching skill, or the user marks the RCA wrong or incomplete, append a record to `gaps/` (input, tools used, final RCA, user feedback).
- Provide `scripts/propose_skill.py` that drafts a new skill markdown from a gap record, for human review before merging.

### 10. Phase 2 (only after 1-9 work and evals show improvement)
- Specialist sub-agents (kube, network/firewall, certs/secrets) run in parallel under a planner, with a synthesizer writing the RCA.
- RCA memory: retrieve similar past RCAs as hints, never as conclusions.
- Proactive health checks (modeled on HolmesGPT's operator mode): scheduled investigations defined by cron (for example certificate expiry sweeps, firewall rule drift, post-deployment verification) that run the same agent loop and post findings to ServiceNow or chat.
- Write the RCA back to the source ServiceNow ticket when the investigation started from one.

## System prompt draft for the investigation agent

```
You are Anchor, a senior SRE investigating production and lower-environment issues across a hybrid on-prem/Azure/AWS estate with 30 Kubernetes clusters, an Istio service mesh, and firewall-protected enclaves.

Method:
1. Understand the report. Use the resolved service context provided. If something is missing, find it with tools rather than asking the user, unless it is truly ambiguous.
2. Call list_skills and load any relevant skills. Treat skills as guidance; if the evidence points elsewhere, follow the evidence.
3. Form 2-4 hypotheses and rank them. For each, name the evidence that would confirm or rule it out.
4. Investigate layer by layer: client -> network/firewall -> ingress/gateway -> mesh sidecar -> service -> dependencies (DB, secrets, certs, credentials). Check both the client side and the server side of every failing call.
5. Plan with todo_write before investigating, and keep the task list current after every tool result. Make parallel tool calls when checks are independent.
6. When a phase of tasks is complete, STOP and evaluate: can I fully answer? Have I reached the real root cause (ask why up to five times)? Did anything new surface (upstream service, firewall, certificate, credentials, recent change)? If yes, plan the next phase.
7. Never conclude from a single signal. Confirm the root cause with at least two independent pieces of evidence, or state clearly that it is unconfirmed.
8. If a tool returns nothing or errors, try another route (different tool, broader time window, different cluster) before concluding.
9. Before the final answer, run a final review: all tasks completed, every claim traced to tool output, unverified items hedged, exact resource names, runnable commands.

Final output (RCA):
- Summary (1-2 sentences)
- Root cause and confidence (confirmed / likely / unconfirmed)
- Evidence (tool, what it showed, timestamp)
- Ruled out
- Not checked (and why)
- Recommended fix and owner
- Suggested follow-ups

Rules: Never invent data. Quote identifiers exactly as seen in tool output. Say "I don't know" when evidence is missing.
```

## Skill template (`skills/_template.md`)

```markdown
---
name: <kebab-case-name>
description: <one line: symptoms that mean this skill applies>
tags: [istio, networking]
---

## Symptoms
- ...

## Likely causes (ranked)
1. ...

## Investigation steps
1. <what to check> -> tool: <anchor-xxx tool> -> confirms / rules out: ...

## Confirming evidence
- ...

## Common false leads
- ...

## Typical fix and owner
- ...
```

## Starter skill: `skills/istio-503.md`

```markdown
---
name: istio-503
description: Clients get HTTP 503 from a service behind Istio (UC, UH, NR, URX response flags)
tags: [istio, 503, networking]
---

## Symptoms
- 503 returned to clients; Envoy response flags such as UC, UF, UH, NR, URX in access logs

## Likely causes (ranked)
1. No healthy upstream: pods not ready or crashing, or readiness probe failing
2. Connection reset or termination: app closing connections, idle timeout mismatch, sidecar not ready at startup
3. Misconfigured VirtualService or DestinationRule (subset, host, port, mTLS mode)
4. Circuit breaker or outlier detection ejecting hosts
5. Network or firewall block between clusters or enclave

## Investigation steps
1. Resolve the service via the catalog: cluster, namespace, hosts, upstream and downstream.
2. Pod state and recent restarts on the server side (anchor-kube).
3. Envoy access logs for the failing requests, including the response flag (anchor-kibana or anchor-kube).
4. VirtualService, DestinationRule, Gateway and PeerAuthentication for the host (anchor-kube).
5. Recent deployments or config changes (anchor-gitlab, anchor-now change tasks).
6. If cross-cluster or enclave traffic is involved, firewall logs (anchor-panorama).

## Confirming evidence
- Response flag matches the hypothesis (UH = no healthy upstream; UC = upstream connection termination) AND a supporting pod or config observation

## Common false leads
- Application errors on the client side that are only a symptom of the 503

## Typical fix and owner
- Depends on cause; name the owning team from the catalog
```

## Acceptance criteria
- [ ] Same test prompt (Istio 503 with vague wording) run in Anchor finds the server side and reaches a confirmed or likely root cause with evidence.
- [ ] Agent runs 10+ tool-call steps when needed and does not stop after 1-3 calls.
- [ ] Agent creates a task list first, updates it after tool calls, and is blocked from answering while tasks are open.
- [ ] Traces show a phase-gate evaluation after each completed phase, and a final review step before the RCA.
- [ ] Each enabled MCP server's instructions file is merged into the system prompt.
- [ ] Large tool outputs are capped and summarized without losing errors or identifiers.
- [ ] Skills load from files; adding a new skill file requires no code change.
- [ ] `scripts/run_evals.py` runs and produces a score report.
- [ ] Traces show reasoning items preserved across tool calls.
- [ ] No regression in the existing UI, API or webhook behavior.

## Deliverables
1. Code changes, in small commits per requirement.
2. `docs/current-state.md` (findings) and `docs/changes.md` (what changed and how to configure it).
3. Initial skills, eval harness, and trace replay script.
