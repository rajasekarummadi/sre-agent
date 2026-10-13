# Prompt: Make Anchor interactive — intent router, developer lookups, guardrails

> **Queued work.** Start only after the RCA accuracy and output fixes (`anchor_spill_followup_fix_prompt.md`) have landed and evals are stable.

You are working in the **Anchor** codebase (`anchor-main`, LangGraph, GPT-5.1, MCP servers: anchor-kube, anchor-gitlab, anchor-panorama, anchor-kibana, anchor-datadog, anchor-now, plus the service catalog). Read the existing code first. Follow the "Do not break existing behavior" rules from `anchor_upgrade_prompt.md` section 0 (feature flag, keep API/UI/webhook contracts, baseline evals before changes, one component per commit).

---

## 1. Goal

Anchor should be useful to **all users, including developers**, not only SREs triaging incidents. A developer who doesn't know where something runs or what is wrong should be able to ask in plain language and get a quick, accurate answer from the right systems.

Today every message goes through the catalog lookup and the full investigation flow. A message like "Hi" wastes tokens and creates an investigation record.

**Target:** route each message by intent. Greetings and general questions get a short reply; quick questions get a fast read-only lookup; real issues get the full investigation. Quick lookups are a first-class path, and investigation is the escalation.

---

## 2. Intent router

Add a `router` node as the first node of the graph, before the catalog node. Put it behind a feature flag `ANCHOR_ROUTER` (default off).

### 2.1 Intents (start with three)

| Intent | Examples | Path |
|---|---|---|
| `chat` | "Hi", "thanks", "what can you do?", "what is a startup probe?" | Short reply, no system tools. For greetings, greet back and suggest what to ask. |
| `lookup` | "Where does usbinsights run?", "Are my pods healthy in UAT?", "Show recent errors for X", "What changed in my last deploy?", "Is traffic allowed from A to B?", "When does the cert on this host expire?" | Read-only tools, step cap ~6, no planning gate or review. |
| `investigate` | "Pods crashing in X", "503s from service Y since 2pm", any ServiceNow incident or webhook | Existing full flow: catalog → plan → five whys → gate → RCA. |

Follow-ups: if the message arrives in an existing investigation's thread, skip the router and continue that investigation with its state. Add separate `knowledge` and `followup` intents later only if usage shows a need.

### 2.2 Routing rules
- `source` of `incident` or `webhook` → always `investigate`, no LLM call.
- Very short greetings or thanks (rules, e.g. ≤3 words matching a greeting list) → `chat`, no LLM call.
- Otherwise one cheap LLM call with structured output: `{intent, confidence}`. Use a smaller/faster model if available.
- Confidence below ~0.7 → `lookup` (the cheaper path that can still use tools). Never default to `investigate` on low confidence.
- Log the intent, confidence and rule used for every message.

### 2.3 Escalation
- If a lookup finds evidence of a problem (crash loops, error spikes, failing probes, denied traffic, expired certs), end the answer with an offer to investigate and show a UI button.
- The button starts `investigate` and passes the lookup's evidence and resolved catalog context, so the investigation doesn't repeat the work.
- The user can also type "investigate this" in the same thread.

---

## 3. The lookup path

### 3.1 Behavior
- **Catalog first:** developers know their service name or URL, not the cluster or namespace. Resolve with `catalog_lookup` before other tools.
- **Ask one short question when ambiguous** (e.g. "UAT or prod?", or several matching services). Don't guess across environments.
- **Read-only tools only**, step cap ~6, parallel calls allowed, existing repeat guard and output spilling apply.
- **No `todo_write`, no review gate**, unless the lookup turns into an investigation via escalation.

### 3.2 Answer style (developers)
- Answer first, in plain language.
- Then the key evidence (2–5 lines): what was checked, where (cluster, namespace, environment), and the result.
- Then the command or link so they can check it themselves next time (e.g. the `kubectl` command, Kibana or Datadog link, GitLab MR).
- No raw YAML or log dumps; quote only the relevant lines.
- Label every fact with its environment (prod, UAT, dev) and cluster.

### 3.3 Chat path
- Greetings: greet back in one line, then suggest 2–3 things to ask, or "paste an incident number or describe what's broken".
- "What can you do?": short capabilities list.
- General technical questions: answer briefly from the model and skills; no cluster tools. If the question is really about a specific system, route to `lookup` instead.
- Stay on SRE and platform topics; politely steer away from unrelated chat.

### 3.4 Conversation memory
- Keep a thread per user so follow-ups work ("and in prod?", "what about yesterday?") without repeating the service name.
- Store resolved catalog context in the thread.

---

## 4. Guardrails (required before opening to developers)

1. **Access control**
   - Identify the user on every request (SSO identity from the UI/API).
   - Scope what Anchor returns by the user's team or entitlements, at minimum by environment (e.g. developers get lower environments by default; prod access follows existing access groups).
   - Enforce the scope in code before tool calls, not only in the prompt. Return a clear "you don't have access to X" message.
2. **Secret redaction**
   - Never return values from Kubernetes Secrets, Vault, env vars that hold credentials, JKS/keystore contents, tokens or connection strings.
   - Redact in the MCP servers (anchor-kube, anchor-gitlab, etc.) before data reaches the model, and again in anchor-main before display.
   - Allow metadata (secret names, keys, owner references, sync status, expiry dates) — just not values.
3. **Audit log**
   - Record user, timestamp, message, intent, tools called with arguments, and environments touched. Retain per company policy.
4. **Read-only stays absolute.** No tool that changes systems is reachable from chat or lookup.
5. **Rate limits** per user and a per-run token cap, so a wider audience can't overload cluster APIs or costs.

---

## 5. UI

- Welcome page: chat input plus starter prompts grouped for developers and SREs (e.g. "Where does my service run?", "Why is my pod restarting?", "What changed in my last deploy?", "Investigate an incident").
- `chat` and `lookup` answers stay in the chat on the welcome page. Only `investigate` creates an investigation record and opens the command center.
- "Investigate this" button on lookup answers that found a problem.
- Thumbs up/down on every answer, stored with the intent and the audit record.

---

## 6. Evals

Add cases for each path; run with the router flag off and on.

- **Chat:** "Hi", "thanks", "what can you do?", "what is a startup probe?" → no system tools, no investigation record, short answer.
- **Lookup (10–15 developer questions):** service location, pod health, recent errors, last deploy changes, firewall path check, cert expiry, ambiguous service name (must ask one question). Pass = correct answer with environment labels and a command or link, within the step cap.
- **Investigate:** existing cases (Vault ownerRef, `usbinsights` read-only `/tmp`) still pass when entered via chat and via webhook.
- **Routing:** borderline phrasings ("my pods look weird", "is X down?") route to `lookup` and offer escalation when a problem is found.
- **Guardrails:** a request for a secret value is refused with metadata only; a user without prod access gets an access message; audit records are written.
- **Regression:** no existing eval case gets worse.

---

## 7. Rollout

1. Build behind `ANCHOR_ROUTER`; SRE team only.
2. Add guardrails (section 4) and verify with evals.
3. Pilot with one developer team, read-only, lower environments first, feedback on.
4. Broaden access after pilot feedback and security review.

## 8. Acceptance criteria

- "Hi" gets a greeting back with suggestions, uses no system tools, and creates no investigation.
- Developer lookups resolve the service via the catalog, answer within the step cap, label environments, and include a command or link.
- Low-confidence routing never starts a full investigation on its own.
- Webhook and ServiceNow intake always investigate.
- Lookups that find a problem offer escalation, and escalation reuses the gathered evidence.
- Secret values never appear in answers or logs; access scope is enforced in code; audit records exist for every request.
- With `ANCHOR_ROUTER` off, Anchor behaves exactly as before.

## 9. Report back

- Router design and how intents and confidence are logged.
- Changes per file.
- Eval results per path, before and after, with tokens and latency per run.
- Any guardrail you couldn't implement and why.
