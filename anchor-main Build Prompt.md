Anchor · SRE agent · build spec

# anchor-main (Anchor SRE agent orchestrator)

The prompt to hand a coding agent for building Anchor's LangGraph orchestrator on OpenAI, with skills, prompts and MCP servers kept as config so they change without code.

Contents

1. [1. Role and goal](#1-role-and-goal)
2. [2. What already exists (do not rebuild)](#2-what-already-exists-do-not-rebuild)
3. [3. Environment facts the design must respect](#3-environment-facts-the-design-must-respect)
4. [4. Tech stack](#4-tech-stack)
5. [5. Repository layout](#5-repository-layout)
6. [6. Config-driven content (the "no code change" requirement)](#6-config-driven-content-the-no-code-change-requirement)
7. [7. LangGraph design](#7-langgraph-design)
8. [8. Runtime prompts (write these files into config.example/prompts/)](#8-runtime-prompts-write-these-files-into-configexampleprompts)
9. [9. RCA schema (structured output)](#9-rca-schema-structured-output)
10. [10. API](#10-api)
11. [11. UI](#11-ui)
12. [12. Security and safety](#12-security-and-safety)
13. [13. Testing and evaluation](#13-testing-and-evaluation)
14. [14. Milestones (stop for review after each)](#14-milestones-stop-for-review-after-each)
15. [15. Acceptance criteria](#15-acceptance-criteria)

Paste this into your coding agent (GitHub Copilot agent mode, Claude Code, etc.) at the root of a new `anchor-main` repo. Build in the milestone order in section 14 and stop for review at the end of each milestone.

## 1. Role and goal

You are a senior Python engineer building **anchor-main**, the central orchestrator of Anchor, our in-house SRE troubleshooting agent.

anchor-main takes a production issue (free-text prompt, ServiceNow incident, pasted logs, or an API call), works out which service is involved using our **service catalog**, investigates it by calling our existing **MCP servers**, and returns a **root cause analysis (RCA)** with evidence. The investigation is a **LangGraph** state graph driving an **OpenAI** model. A web UI shows the investigation live.

Hard requirement: **skills, prompts, model settings and MCP server registrations are data, not code.** Ops engineers must be able to add or change a troubleshooting skill, tweak a prompt, or register a new MCP server by editing files in a git repo and pushing, with no code change, rebuild or redeploy of anchor-main.

## 2. What already exists (do not rebuild)

- **MCP servers** (Python, tested with MCP Inspector and GitHub Copilot):
- `anchor-kube`: 30+ Kubernetes clusters (AKS/Rancher), 20+ read tools (pods, events, logs, secrets metadata, Istio objects…)
- `anchor-gitlab`: repos, MRs, CI/CD pipeline and job failures
- `anchor-panorama`: Palo Alto firewall policies across on-prem, Azure and AWS
- `anchor-kibana`: ELK log search
- `anchor-datadog`: APM, metrics, monitors
- `anchor-now`: ServiceNow incidents and change tasks
- Planned later: `anchor-f5`, `anchor-venafi`, `anchor-extrahop`, `anchor-esxi`. Adding them must be config-only.
- **Catalog service**: PostgreSQL database with metadata for every microservice across the clusters: services, namespaces, clusters, hosts they expose, Istio Gateways/VirtualServices/DestinationRules/ServiceEntries, certificates (JKS metadata only), DNS records, F5 virtuals and pool members, owning team, repo. Includes views that answer "who serves this hostname" and trace a client → egress → F5 → ingress → server path. Refreshed daily by a Python sync job. Treat its schema as given; read it from the DB and wrap it in a `CatalogClient`.

## 3. Environment facts the design must respect

- Multi-tier network with a firewall-protected **enclave**. Some checks (e.g. OpenSSL against enclave-only domains) only work from inside the enclave, so the agent must say "needs an enclave check" rather than guess.
- **Istio** service mesh; cross-namespace and cross-team traffic often goes via an egress gateway, external DNS and an F5 VIP.
- Recurring failure classes: firewall access, expired certs on enclave-only domains, bad NHID credentials, bad client certs stored as JKS in K8s secrets or code, Istio 503s, CI/CD failures, bad deploys.
- Developers' incident reports are often vague. The agent must resolve the service before investigating and ask one targeted question when it can't.
- POC credentials: no service account yet. Identity for each MCP server comes from config so we can swap to NHIDs / Workload Identity later without code changes.
- **MVP is read-only.** No tool that mutates anything may be callable. Predictive "precognition" and auto-fix are out of scope (UI shows them as disabled placeholders).

## 4. Tech stack

- Python 3.11+, FastAPI, Pydantic v2, uvicorn
- **LangGraph** for orchestration; `langchain-openai` for the model; `langchain-mcp-adapters` (`MultiServerMCPClient`) for MCP tools
- **OpenAI via config**: support both `openai` and `azure_openai` providers (`ChatOpenAI` / `AzureChatOpenAI`), selected in `config/models.yaml`. Different nodes may use different models (cheap model for classify, strong model for investigate and RCA).
- PostgreSQL: LangGraph `AsyncPostgresSaver` checkpointer, an `investigations` table, and `pgvector` for past RCAs
- MCP servers reached over **streamable HTTP** (long-lived services), not stdio
- UI: React + Vite + TypeScript, consuming a Server-Sent Events stream
- Packaging: Dockerfile, Helm chart, `docker-compose.yml` for local dev (Postgres + anchor-main + UI)

## 5. Repository layout

```
anchor-main/
  app/
    api/            # FastAPI routers: investigations, webhooks, admin, stream
    graph/          # LangGraph state, nodes, routing, builder
    catalog/        # CatalogClient
    mcp/            # MCP client factory, tool filtering, read-only guard
    llm/            # model factory from config
    registry/       # SkillRegistry, PromptRegistry, ConfigRegistry (hot reload)
    events/         # event bus -> SSE
    store/          # investigations repo, pgvector RCA memory
    security/       # redaction, audit log
  ui/               # React app
  tests/
  evals/            # replay harness + incident fixtures
  config.example/   # example of the external config repo (see section 6)
```

Code never hardcodes a skill, prompt, model name or MCP server URL.

## 6. Config-driven content (the "no code change" requirement)

All of the following live in a **separate git repo, `anchor-config`**, mounted into the pod at `ANCHOR_CONFIG_DIR` (default `/etc/anchor`) and kept in sync by a `git-sync` sidecar. Locally it's just a folder.

```
anchor-config/
  config/
    models.yaml        # provider, deployment/model per node, temperature, timeouts
    mcp_servers.yaml   # name, url, auth ref, enabled, read-only tool allowlist
    limits.yaml        # tool-call budget, recursion limit, timeouts, max output sizes
  prompts/
    intake.md
    classify.md
    investigate.md
    evaluate.md
    rca.md
    clarify.md
  skills/
    istio-503/SKILL.md
    cert-expiry/SKILL.md
    firewall-access/SKILL.md
    nhid-credentials/SKILL.md
    jks-client-cert/SKILL.md
    cicd-failure/SKILL.md
    bad-deploy/SKILL.md
    generic-triage/SKILL.md   # fallback when nothing matches
```

### 6.1 Hot reload rules

- `SkillRegistry`, `PromptRegistry` and `ConfigRegistry` load everything at startup, then watch the directory (`watchfiles`) and reload on change. Also expose `POST /v1/admin/reload`.
- Every file is validated (Pydantic) on load. **An invalid file is rejected and the previous good version stays active**; the error is logged and shown at `GET /v1/admin/config/status`.
- Each loaded item has a version (git commit SHA from git-sync, else file hash). Every investigation records the versions it used, so an RCA can be traced to the exact skill and prompt text.
- An investigation that is already running keeps the snapshot it started with.
- Adding a server in `mcp_servers.yaml` (e.g. `anchor-f5`) makes its tools available on the next investigation with no restart.

### 6.2 Skill file format

A skill is Markdown with YAML frontmatter. The frontmatter is machine-read; the body is injected into the investigator's prompt when the skill is selected.

```markdown

name: istio-503
version: 3
description: Istio 503/UF/UH/NR errors between services, including cross-namespace traffic via egress gateway, external DNS and F5 VIP.
match:
  failure_classes: [istio_503]
  keywords: ["503", "upstream connect error", "no healthy upstream", "UF", "NR", "envoy"]
tools:            # allowlist: server:tool, glob patterns allowed
  - anchor-kube:get_pods
  - anchor-kube:get_events
  - anchor-kube:get_istio_*
  - anchor-kube:get_proxy_logs
  - anchor-kibana:search_logs
  - anchor-datadog:query_apm
  - anchor-panorama:check_policy
checks:           # deterministic playbook, run before the LLM loop
  - id: server_pods_ready
    tool: anchor-kube:get_pods
    args: { cluster: "{{service.cluster}}", namespace: "{{service.namespace}}", selector: "{{service.selector}}" }
    expect: "all(p.ready for p in result.pods)"
    on_fail: "Server pods not ready"
  - id: destination_rule_tls
    tool: anchor-kube:get_istio_destination_rules
    args: { cluster: "{{service.cluster}}", host: "{{service.host}}" }
    expect: "len(result.items) > 0"
    on_fail: "No DestinationRule for the server host"
evidence_required: 2      # independent sources before stating a root cause
max_tool_calls: 20

## How to investigate
1. Resolve both ends from the catalog: client service and the server behind the hostname. Use the catalog path view (client → egress → DNS → F5 → ingress → server).
2. Read the envoy response flag in the client's proxy logs (UF, UH, NR, URX…) and use it to pick the hop to check first.
3. ...
## Known causes
- mTLS mode mismatch between PeerAuthentication and DestinationRule
- ...
## When to stop and ask
- If the server side isn't in the catalog, ask for the server hostname. Don't guess.
```

`expect` is evaluated with a **sandboxed expression evaluator** (e.g. `simpleeval`), never `eval`. `args` are rendered with sandboxed Jinja2 against the investigation state. A check either passes, fails (with its `on_fail` text as a finding), or errors (recorded, not fatal).

Skill selection is dynamic: the classify prompt is given the `name` and `description` of every loaded skill, so a new skill folder is selectable as soon as it is pushed.

### 6.3 `mcp_servers.yaml`

```yaml
servers:
  - name: anchor-kube
    url: http://anchor-kube.anchor.svc:8000/mcp
    transport: streamable_http
    auth: { type: bearer, secret_ref: anchor-kube-token }   # resolved from env / K8s secret
    enabled: true
    read_only_tools: ["get_*", "list_*", "describe_*", "search_*"]
  - name: anchor-f5
    url: http://anchor-f5.anchor.svc:8000/mcp
    enabled: false
```

Only tools matching `read_only_tools` are ever bound to the model. Anything else is dropped at load and logged.

## 7. LangGraph design

### 7.1 State

```python
class InvestigationState(TypedDict):
    investigation_id: str
    source: Literal["prompt", "incident", "logs", "api", "webhook"]
    raw_input: str
    incident: IncidentSummary | None        # service hint, env, symptom, start time, impact
    service: CatalogMatch | None            # cluster, namespace, hosts, repo, owner, path
    candidates: list[CatalogMatch]          # when ambiguous
    context_pack: dict[str, ToolResult]     # baseline evidence
    skill: str | None
    check_results: list[CheckResult]
    hypotheses: list[Hypothesis]            # text, status (open/confirmed/ruled_out), evidence ids
    evidence: list[Evidence]                # id, source tool, summary, link, timestamp
    messages: Annotated[list[AnyMessage], add_messages]
    tool_calls_used: int
    seen_calls: set[str]                    # hash of (tool, args) for dedupe
    confidence: int                         # 0-100
    status_note: str                        # one-line, user-facing, for the UI
    rca: RCA | None
    config_versions: dict[str, str]
```

### 7.2 Nodes and edges

```
intake ─► resolve_service ─┬─► context_pack ─► classify ─► playbook ─┬─► rca ─► publish ─► END
              ▲            │                                         │
              └── clarify ◄┘ (ambiguous / not found)                 └─► investigate ⇄ tools
                                                                            │
                                                                            ▼
                                                                         evaluate ─┬─► investigate (more evidence needed, budget left)
                                                                                   └─► rca
```

1. **intake** (LLM, small model, `prompts/intake.md`): turn any input into `IncidentSummary`. For `incident` source, fetch the ticket via `anchor-now` first. Structured output only.
2. **resolve_service** (no LLM): query the catalog by service name, hostname, URL, IP, namespace or deployment name. Exactly one match → continue. Several or none → `clarify`.
3. **clarify**: `interrupt()` with one targeted question and the top candidates (prompt in `prompts/clarify.md`). The UI shows it; the user's answer resumes the graph back at `resolve_service`. Webhook-sourced runs post the question as a ServiceNow work note and wait.
4. **context_pack** (no LLM, parallel): pod health and restarts, recent deploys and pipeline runs, error-rate change in the incident window, open change tasks, related recent incidents. What to fetch is listed in `limits.yaml` under `context_pack`, so it's config too.
5. **classify** (LLM, small model, `prompts/classify.md`): pick a failure class and **one skill** from the loaded skills; fall back to `generic-triage`.
6. **playbook** (no LLM): run the skill's `checks`. If checks plus context pack already meet `evidence_required` for a single cause, go straight to `rca`; otherwise `investigate`.
7. **investigate** (LLM, strong model, `prompts/investigate.md` + skill body): tools bound = skill allowlist ∩ server read-only allowlist. Before each step the model updates `hypotheses` and `status_note`.
8. **tools**: `ToolNode` wrapper that enforces the read-only guard, per-tool timeout, output truncation, secret redaction, dedupe (`seen_calls`), increments `tool_calls_used`, appends `Evidence`, and emits UI events.
9. **evaluate** (LLM, `prompts/evaluate.md`): is there a cause backed by ≥ `evidence_required` independent sources? Set `confidence`. Route back to `investigate` if not, and budget remains.
10. **rca** (LLM, strong model, `prompts/rca.md`): `with_structured_output(RCA)`. Always reachable: budget exhaustion, recursion limit or errors still produce an RCA with low confidence and a list of what's unknown.
11. **publish**: save to `investigations`, embed into pgvector, post a work note to ServiceNow when the source is an incident or webhook, emit `rca_ready`.

### 7.3 Loop control

- `tool_calls_used` vs `limits.max_tool_calls` (skill can lower it), checked in the router
- LangGraph `recursion_limit` as a hard stop (config)
- Dedupe: identical (tool, args) calls return the cached result plus a note telling the model it already has this
- Wall-clock timeout per investigation (config)
- Any stop condition routes to `rca`, never to a dead end

### 7.4 Past incidents

Before `investigate`, retrieve the 3 most similar past RCAs from pgvector (by symptom + service) and add them to the prompt as hints, clearly marked as "past cases, verify before relying on them".

## 8. Runtime prompts (write these files into `config.example/prompts/`)

Keep each prompt short and specific. Shared rules for every LLM node:

- Use only facts from tool results, the catalog or the incident. Every claim in the RCA must cite an evidence id.
- Never invent service names, hosts, namespaces or timestamps. If a field is missing, say so.
- Read-only: never propose running a command as if it were done.
- Enclave-only checks (OpenSSL on enclave domains, etc.) are listed as "needs enclave check" with the exact command for a human to run.
- `status_note` is one plain sentence for the UI about what you're doing now. It is not hidden reasoning.

**investigate.md** must also say: - Start from the skill's "How to investigate" steps, then adapt. - Keep 2–4 open hypotheses. For each tool call, state which hypothesis it tests. - Prefer one targeted call over broad sweeps; prefer the catalog path over guessing hops. - Stop calling tools when one hypothesis has enough independent evidence or all are ruled out.

**rca.md** output must match the `RCA` schema (section 9) and be readable by a non-SRE in 15 seconds at the top, with engineering detail below.

## 9. RCA schema (structured output)

```python
class RCA(BaseModel):
    title: str
    summary: str                    # 2-3 plain sentences
    impact: str
    root_cause: str | None          # None if not established
    confidence: Literal["high", "medium", "low"]
    confidence_score: int           # 0-100
    timeline: list[TimelineEntry]   # time, event, evidence_id
    evidence: list[EvidenceRef]     # id, source, finding, link
    ruled_out: list[str]            # hypotheses eliminated, with evidence ids
    remediation: list[str]          # proposed, not executed
    needs_human: list[str]          # enclave checks, missing access, open questions
    affected_path: list[HopStatus]  # hop name, via server, status: ok/suspect/fault/unknown
    skill_used: str
    config_versions: dict[str, str]
```

Render it as Markdown for ServiceNow work notes and as JSON for the UI and API.

## 10. API

- `POST /v1/investigations` — body: `{ source, input, env?, since? }` → `{ investigation_id }`
- `GET /v1/investigations/{id}` — state summary and RCA when done
- `GET /v1/investigations/{id}/events` — SSE stream (section 11)
- `POST /v1/investigations/{id}/answer` — resume after `clarify`
- `GET /v1/investigations?limit=` — recent list for the Welcome page
- `POST /v1/webhooks/servicenow` — HMAC-verified; starts an investigation for configured priorities
- `GET /v1/status` — MCP server health, catalog last sync time, loaded skills
- `GET /v1/admin/config/status`, `POST /v1/admin/reload`

## 11. UI

Design reference: the "SRE Agent Console" canvas (pages "1 · Welcome" and "2 · Anchor — command center"). Match its look: near-black grid background `#07090D`, text `#D9E1EA`, headings `#F4F8FC`, accent `#7FD4FF`, secondary `#B49CFF`, success `#8FE3A5`, warning `#F2C27A`, fault `#FF8F8F`; fonts Space Grotesk (UI) and JetBrains Mono (labels, data). Responsive down to phone width.

### Page 1 — Welcome

- Header: Anchor wordmark, nav (Home, Command center, Investigations), signed-in user
- Hero: greeting, "What's broken in prod?", one-line explainer
- Prompt card with three tabs: **Ask in plain words** (textarea), **Incident number** (INC input), **Paste logs** (monospace textarea). Env and "since" pickers. **Investigate** button → `POST /v1/investigations` → navigate to page 2
- "Try asking" example chips (loaded from `anchor-config`, so they're editable too)
- Recent investigations with status: RCA ready / running / needs input
- Side panel: MCP server status and catalog sync time from `GET /v1/status`; auto-intake indicator

### Page 2 — Command center (one investigation)

Driven entirely by the SSE event stream:

| UI panel | Fed by |
| --- | --- |
| Live header (incident id, title, elapsed) | `investigation_started` |
| Agent core + tool orbit (one node per MCP server, glows while called) | `tool_call_started` / `tool_call_finished` |
| "Anchor is working" line + feed | `status_note`, `tool_call_finished` summaries |
| Confidence ring + current leading hypothesis | `hypothesis_updated` |
| Live path (hops: ok / suspect / fault / unknown) | `hop_status` (from catalog path + checks + evidence) |
| Clarify card (question + candidate buttons) | `needs_input` |
| RCA panel (summary, root cause, evidence links, ruled out, needs human, remediation) | `rca_ready` |
| Time machine scrubber | replay of stored events for this investigation |
| Precognition and "Approve fix" | shown disabled, labelled "coming later" |

Event envelope: `{ id, investigation_id, ts, type, node, payload }`. Store every event so the scrubber can replay a finished investigation.

## 12. Security and safety

- Read-only guard at two layers: server allowlist at load, and a check in the tools node at call time
- Redact secrets, tokens, private keys and cert bodies from tool output before it reaches the model, the UI or the DB (pattern list in config)
- Audit log: every tool call with args, caller, investigation id, duration, result size
- Model provider keys and MCP tokens only from env / K8s secrets, referenced by name in config
- Webhook HMAC verification; API auth via the company SSO (OIDC) for the UI and a service token for API callers
- Untrusted text (ticket bodies, logs, skill bodies from git) is wrapped as data in prompts, never treated as instructions

## 13. Testing and evaluation

- Unit tests for registries (valid reload, invalid file keeps old version), check evaluator, router logic, redaction
- Graph tests with fake MCP tools and a fake model
- **Replay eval** in `evals/`: 20–30 resolved past incidents as fixtures (input, recorded tool responses, known root cause). Score: root cause correct, evidence cited, tool calls used, time. Run it on every change to prompts or skills (CI job in `anchor-config` too), so a pushed skill change is checked before it goes live.
- Include the Istio 503 cross-namespace case (egress gateway → external DNS → F5 VIP → ingress) as a must-pass fixture.

## 14. Milestones (stop for review after each)

1. Skeleton, config registries with hot reload, model factory, MCP client with read-only filtering, `/v1/status`
2. Graph: intake → resolve_service → clarify → context_pack, with the catalog client and checkpointer
3. classify → playbook → investigate ⇄ tools → evaluate → rca → publish, with K8s, GitLab and Kibana first
4. API, SSE events, ServiceNow webhook and work-note posting
5. UI pages 1 and 2 wired to the API
6. pgvector past-RCA memory, replay eval harness, the 8 starter skills
7. Remaining MCP servers (Panorama, Datadog, Now), Helm chart, docs

## 15. Acceptance criteria

- A new skill folder pushed to `anchor-config` is selected by classify on the next investigation with no restart
- A broken skill file is rejected, the previous version keeps working, and the error shows in `/v1/admin/config/status`
- Changing `models.yaml` from OpenAI to Azure OpenAI (or swapping model per node) needs no code change
- Enabling `anchor-f5` in `mcp_servers.yaml` exposes its read-only tools on the next run
- The Istio 503 fixture produces a correct RCA citing ≥2 independent sources
- A vague prompt with no catalog match produces one clarify question, not a guessed RCA
- Budget exhaustion still yields an RCA with low confidence and a `needs_human` list
- No write/mutating tool can be called, verified by a test that registers one
- Every RCA records the skill and prompt versions it used