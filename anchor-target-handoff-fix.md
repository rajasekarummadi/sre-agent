# Anchor: Target Handoff & NEEDS INPUT Loop Fix

Status: approved plan, not yet implemented · Owner: SRE (Anchor) · Implementer: GitHub Copilot
Branch: `feature/catalog-resolver-integration`
Must merge **before** `anchor-question-coverage-and-skills.md` starts.

---

## 0. Instructions for Copilot

1. This document restates the plan you proposed and the owner approved, plus the owner's additions. Function and field names come from your earlier trace; **verify each against the current code** before changing it, and report any difference.
2. Deliver in **two slices**. Stop after slice 1, run the replay in Section 5, report results, and wait for approval before slice 2.
3. Track progress in `docs/target-handoff-status.md`.
4. No regressions: planner mode stays default; contracts (API, ServiceNow webhook, UI payloads, checkpoints) change additively; new state fields must be safe when absent in old checkpoints.
5. Every behavior change gets tests parameterized for **both** `ANCHOR_LOOP_MODE=planner` and `native`.

---

## 1. The failure

Thread `45a7ca8e-ad44-41a7-a24a-926ae0f12c12`, investigation `60c7d25e-a1fa-411b-9d93-5baf3deae568`.

1. User asked about `usb-dss-accounts` in uat5. Anchor resolved cluster `digital-obc-k8-pci-uat02`, namespace `apl-digital-secure-banker-services-uat5`, and asked for confirmation.
2. User replied "yes". Lookup succeeded: 2 pods Running/Ready, 4 restarts each, on different nodes.
3. User asked: "What caused the 4 restarts on each pod?"
4. Anchor started an investigation and went into **NEEDS INPUT**, asking for the target again. The user answered "usb-dss-accounts in banker uat5 namespace". Anchor asked again.

Result: 2 interrupts, 1 clarification, **0 diagnostic tool calls**. The target was known and confirmed the whole time.

---

## 2. Root causes (from Copilot's trace)

| # | Cause | Where |
|---|---|---|
| R1 | **Primary.** Escalation dispatch copies the lookup seed only when `decision.rule == "user_escalation"`. This message was `rule=model, intent=investigate`, so `seed={}`. The investigation started with only the question and `env=uat5`. | `_send` escalation dispatch |
| R2 | Misleading UI text: "Investigation started with the available lookup context" is shown even on the empty-seed branch. | same |
| R3 | Clarification merges structured cluster/namespace only when `source in {"incident","webhook"}`. This investigation had `source=prompt`. | clarification merge |
| R4 | `_identifier_terms` used the whole sentence "usb-dss-accounts in banker uat5 namespace" as one search term → zero matches → asked again. `lookup_catalog_term` already extracts `usb-dss-accounts` correctly. | `_identifier_terms` |
| R5 | `resolve_service` has no "this exact target was already confirmed" contract, so seeded matches can re-trigger confirmation. | `resolve_service` |
| R6 | Attachment to an investigation is too sticky: any message during NEEDS INPUT is consumed as the answer; finished investigations force "start a new thread". | thread/investigation routing |
| R7 | Resume depends on the in-worker `_states` dict rather than the Postgres checkpoint. A worker restart loses the pending state. | resume path |
| R8 | No size bounds on intake prefetch, native bootstrap and catalog confirmation responses. Observed: `Interactive model admission denied … limit=1000000 … input_bound=3552747`, and a confirmation card shown to the user ending in `[TRUNCATED 5670984 chars; narrow query/paginate]`. | intake, bootstrap, confirmation card |
| R9 | `lookup_catalog_term` picks the first identifier in "compare A and B" instead of keeping both. | extractor |

---

## 3. Slice 1 — Target handoff (fixes R1–R5, R9)

### 3.1 Seed for every investigation
- Pass the lookup seed for **every** decision that starts an investigation, regardless of `decision.rule` (`user_escalation`, `model`, or any other).
- Extend the seed **additively** with confirmation metadata:
  ```
  confirmed_target:
    service, cluster, namespace, environment
    confirmed_at, confirmed_by (user | exact_match)
    source_turn_id
  ```
- Fix R2: the UI says "started with lookup context" only when a non-empty seed was passed; otherwise say what is missing.

### 3.2 State
Extend `InvestigationState` additively:
- `confirmed_target` (as above).
- `clarification_progress`: questions asked (normalized), answers received, candidates considered, attempt count.
Both default to empty and are safe for old checkpoints.

### 3.3 One shared extractor
- Move identifier extraction and narrowing into a shared helper used by lookup, clarification, and graph resolution. Base it on `lookup_catalog_term`.
- Apply it **regardless of `source`** (`prompt`, `incident`, `webhook`).
- Preserve ambiguity: "compare A and B" yields both A and B, never just the first (R9).
- Merge structured cluster/namespace/environment from the clarification answer for all sources (R3).

### 3.4 Honor confirmed targets
`resolve_service` accepts `confirmed_target`. **Auto-proceed without asking** only when all of these hold:
1. Environment unchanged from the confirmed target.
2. Exactly one distinct service/cluster/namespace remains.
3. Identity is an exact match or already confirmed.
4. Authorization check passes.
5. No conflicting identifiers in the new message.

Otherwise show the candidates with **provenance** (where each came from: catalog, lookup, user text) and ask once.

### 3.5 Same-target rule (owner addition)
- A follow-up with **no new identifier** ("what caused the restarts?", "check the logs") inherits the confirmed target.
- A follow-up naming a **different service or environment** resolves fresh and does not reuse the old target.

### 3.6 No-progress guard
- Never ask the same clarification twice. If `clarification_progress` shows the same normalized question already asked and the answer narrowed candidates to one, proceed. If not, show the remaining candidates with provenance instead of repeating the question.
- Maximum 2 clarification rounds per investigation; then proceed with what's known and state the uncertainty in the answer. *(Addition to the approved plan; confirm with the owner before implementing.)*

---

## 4. Slice 2 — Routing, resume and size bounds (fixes R6–R8)

### 4.1 Classify before attaching
While an investigation is in NEEDS INPUT, classify the new message first:
- **Answer to the pending question** → resume the investigation.
- **Side question** (e.g. "what namespace is that in?") → answer it, keep the investigation pending, remind the user what's still needed.
- **New request** → handle normally; the pending investigation stays resumable.
- A finished investigation does not force "start a new thread"; follow-ups use the same-target rule.

### 4.2 Resume from checkpoint
Resume from the Postgres checkpoint, not the in-worker `_states` dict. If the checkpoint is missing, show an explicit recovery message with the known target instead of silently starting over. Test with a simulated worker restart.

### 4.3 Bounded payloads
- Confirmation cards are built from **fixed fields only** (service, cluster, namespace, environment, match reason). Never embed raw tool output.
- *(The next two bullets are additions to the approved slice 2; they come from the same audit. Confirm scope with the owner — they may move to WS7 context compaction instead.)*
- Intake prefetch and native bootstrap use bounded projections (counts, top N, summaries with evidence IDs), checked against the model's input limit **before** the call.
- Pass evidence from lookup to investigation as **evidence IDs plus bounded summaries**, so the investigation can cite lookup findings without re-fetching or receiving the full payload.

---

## 5. Replay after slice 1 (required before slice 2)

Rerun thread `45a7ca8e-ad44-41a7-a24a-926ae0f12c12` from the message "What caused the 4 restarts on each pod?" in both modes. Report:

| Metric | Expected |
|---|---|
| Seed passed to investigation | service, cluster, namespace, env, `confirmed_target` |
| Interrupts / NEEDS INPUT | **0** |
| Clarifications | **0** |
| First 3 tool calls | Diagnostic (e.g. pod status / termination reason / previous logs / events) on the confirmed target |
| UI message | "started with lookup context" only because the seed is non-empty |

---

## 6. Tests (parameterized for planner and native)

1. Replay of thread 45a7ca8e (Section 5).
2. `rule=model, intent=investigate` after a confirmed lookup → seed present, no confirmation asked.
3. `source=prompt` clarification answered with a sentence ("usb-dss-accounts in banker uat5 namespace") → extracts the service, merges namespace/env, proceeds.
4. Follow-up naming a different service → fresh resolution, old target not reused.
5. Follow-up with a different environment → fresh resolution.
6. "Compare A and B" → both identifiers kept.
7. Same clarification would repeat → no-progress guard proceeds or shows candidates; never asks the identical question twice.
8. *(slice 2)* Side question during NEEDS INPUT → answered; investigation still pending.
9. *(slice 2)* Worker restart during NEEDS INPUT → resumes from checkpoint.
10. *(slice 2)* Tool output of several MB → confirmation card stays within fixed fields; no `[TRUNCATED …]` text reaches the UI; no admission-denied error.
11. Old checkpoint without the new fields loads and runs.

---

## 7. Out of scope
- Typed tool errors (namespace_denied, rbac, not_found, auth, timeout).
- Connecting Kibana and Datadog.
- Filling catalog repository mappings (e.g. `usb-dss-accounts` shows "Repository: not reported").
- Health checks that report a server as connected without proving it is usable (found in the same audit).
- The false "unverified" RCA verdict follow-ups for `bbds-grphqldep` (structured `root_cause`/`claims[]`, verifier after bounces run out, `ruled_out` hypotheses) — sent to Copilot separately.
- Question-family routing (covered by `anchor-question-coverage-and-skills.md`, which starts after slice 1 merges).

## 8. Acceptance

| Slice | Gate |
|---|---|
| 1 | Tests 1–7 and 11 pass in both modes; replay shows 0 interrupts and diagnostic first calls; owner approves |
| 2 | Tests 8–10 pass in both modes; full existing test and replay suites pass; owner approves |
