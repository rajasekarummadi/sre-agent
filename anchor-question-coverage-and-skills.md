# Anchor: Question Coverage, Environment Discovery & Skills

Status: proposed (v2) · Owner: SRE (Anchor) · Implementer: GitHub Copilot
Related: `Anchor Agent Harness & Loop Redesign.md`, `harness-redesign-status.md`, the target-handoff fix (slices 1–2) for thread `45a7ca8e-ad44-41a7-a24a-926ae0f12c12`.

---

## 0. Instructions for Copilot (read first)

1. **Verify before implementing.** For each phase, first confirm against the code how things work today and report differences from this document. Where this document is wrong about the code, the code wins; tell me.
2. **Work in phases. Stop after each phase** with a short report and wait for approval.
3. **Ask, don't guess.** For anything about our environment, follow the clarification loop in Section 6.5. Never write an environment fact into a skill or config unless it is `owner_stated` or `confirmed`.
4. **Track progress** in `docs/question-coverage-status.md`: one row per phase with status, files changed, tests, open questions.
5. **No regressions:** planner mode stays default and unchanged; all contracts (MCP, API, ServiceNow webhook, UI payloads, checkpoints) change additively only; new state fields must be safe when absent in old checkpoints.
6. **Read-only always.** Nothing writes to clusters, GitLab, ServiceNow, Panorama or Azure. No `exec`, `port-forward`, `cp`, or bulk log pulls.
7. **Never read or store secret values.** This covers Kubernetes `Secret` data, **Helm release secrets** (list labels/metadata only, never decode), Vault values, private keys and tokens. Certificates: metadata only (issuer, SANs, expiry).
8. Do not start until the target-handoff fix (slice 1) is merged.

---

## 1. Problems this solves

| # | Problem |
|---|---------|
| P1 | We don't know what developers actually ask Anchor, or which questions it answers correctly. |
| P2 | Anchor only routes "lookup vs investigate". It doesn't know *how* to answer each type of question, so the model improvises. |
| P3 | Kubernetes, Istio and Helm skills are generic and don't reflect our environment: 27 clusters across on-prem and AKS, channel/environment layout, naming conventions, custom blue/green, the on-prem → Azure migration. |

---

## 2. Constraints

- Enclave/firewall-restricted environment; everything runs inside it.
- PCI-scoped clusters exist (e.g. `digital-obc-k8-pci-uat02`). Survey output is internal and redacted.
- **Copilot never holds a raw kubeconfig.** Cluster access is through the tiers in Section 6.2.
- Kibana and Datadog are **not currently connected**. Playbooks must handle their absence explicitly (e.g. Istio access-log response flags can't be read without them).

---

## 3. Phase 0 — Discovery (no code changes)

Report:
1. Current intent classification: file/function, intents, how lookup vs investigate is chosen.
2. All loaded skills (~22): name, trigger, required tools. Flag duplicates and skills referencing tools not in the discovered menu.
3. All discovered tools (~51): server, name, read-only status, what each returns. Note specifically whether any tool can read: Helm release metadata, Istio proxy config / `istioctl analyze`-style checks, Envoy access logs, events older than the cluster's event TTL.
4. Eval case format and replay entry point.
5. Where threads and 👍/👎 feedback are stored.
6. How the target resolver currently maps environment words ("uat5", "banker") to cluster/namespace.

---

## 4. Phase 1 — Question bank pipeline (solves P1)

Build `python -m anchor.questionbank build`, read-only, inside the enclave.

### 4.1 Sources
1. Anchor threads and investigations, with 👍/👎 and outcome.
2. ServiceNow via anchor-now: 12 months of incidents/requests, rewritten as the question a developer would have asked.
3. Optional channel exports (Slack/Teams) if provided as files.
4. Synthetic fill for families with fewer than 10 real questions (`source: synthetic`).

### 4.2 Processing
Redact secrets, tokens, personal names, emails, phone numbers, requester identity; keep service/namespace/cluster/environment names. Remove near-duplicates. Classify into a family (Section 5). Tag each question with **channel** and **environment** when detectable (uses the environment model from Phase 3 once it exists). Rank by frequency and impact.

### 4.3 Output
`evals/cases/questions/<family>/<id>.yaml`, existing case format plus additive fields:

```yaml
id: qb-exposure-0007
family: exposure_tls
source: servicenow            # anchor_thread | servicenow | channel_export | synthetic
source_ref: INC0123456
question: "Which external hostnames does usb-dss-accounts expose, and does the gateway require a client certificate?"
target_hint: {service: usb-dss-accounts, environment: uat5, channel: banker, platform: onprem}
expected_route: answer        # lookup | answer | investigate
expected_answer: null
must_inspect: []
review: pending               # pending | needed_owner | reviewed | rejected
```

### 4.4 Feedback hook
A 👎 in the console creates a draft case from that thread.

### 4.5 Owner review
Top 20 cases → `review: needed_owner`; owner fills `expected_answer` and `must_inspect`. Others graded by an LLM judge against the family's answer contract.

**Done when:** counts per family/source/channel/platform reported; files written; hook works; a test scans generated files for secret patterns.

---

## 5. Phase 2 — Question families & routing (solves P2)

### 5.1 Family definition
`config/question_families/<family>.yaml`:

```yaml
id: exposure_tls
description: How a service is exposed and its TLS/mTLS posture.
examples: ["Which external hostname does this API expose?", "Does the gateway require a client cert?"]
route: answer                 # lookup | answer | investigate
skill: exposure-and-tls
required_tools: [...]
optional_tools: [...]
answer_contract:
  - Separate DECLARED (config) from OBSERVED (live) findings.
  - Cite evidence IDs for each claim.
  - If a required tool is unavailable, state what could not be verified.
```

### 5.2 Initial families (adjust from Phase 1 counts)

| Family | Route | Typical question |
|---|---|---|
| `status` | lookup | Is X up in uat5? Which version is live? |
| `exposure_tls` | answer | Hostnames, client certs, TLS versions |
| `routing_traffic` | answer / investigate | Why 404/503? What's the blue/green split? |
| `egress_firewall` | investigate | Why can't X reach Y? |
| `secrets_config` | answer / investigate | Is the Vault secret synced? Which config is deployed? |
| `deploy_ci` | answer / investigate | What's deployed where? Why did the pipeline/release fail? |
| `migration` | answer | Is X running on-prem, AKS or both? Where does traffic go? |
| `failure_investigation` | investigate | Restarts, 5xx, latency |
| `capacity_resources` | answer | Limits, HPA, node pools |
| `other` | answer | Logged for new families |

### 5.3 Router changes
1. Classify into a family after the target is resolved.
2. The family decides the route. **`answer` families never start an RCA investigation.**
3. Capability check: compare `required_tools` to the discovered menu; run what's possible and say what couldn't be verified.
4. Load the family's skill(s) plus the environment overlay (Section 7.1).
5. Low confidence → `other` behavior and log for the bank. Never ask the user to pick a family.

### 5.4 Worked example: `exposure_tls`
1. Resolve target. 2. VirtualServices routing to the service → `hosts`, `gateways`. 3. Each Gateway server: `tls.mode` (`MUTUAL` = client cert required, `OPTIONAL_MUTUAL` = requested not required, `SIMPLE` = none, `PASSTHROUGH` = check the workload), protocol versions (unset → Istio/Envoy defaults for the installed version), credential metadata. PeerAuthentication does not govern external clients. 4. Determine the **termination point** (F5, Azure Application Gateway, other LB in front of the gateway); if TLS terminates upstream, Gateway config is not what clients see. 5. DNS + live probe labeled by vantage point. 6. Answer per contract.

**Done when:** family configs exist, router uses them in both modes, capability check works, `exposure_tls` replay passes.

---

## 6. Phase 3 — Environment discovery (interactive)

Goal: build an accurate model of our environment, confirmed by the owner, that both code and skills use.

### 6.1 Seed facts (`owner_stated`)

**Platforms**
- 18 on-prem Kubernetes clusters, 9 AKS clusters.
- Migration in progress on-prem → Azure. As customers move to Azure, some on-prem namespaces will be decommissioned.

**Environments:** IT (3), UAT (4), performance, preprod, employee, production.

**Channels**
- Consumer: OLB, mobile.
- Partner.
- Banker.
- Branch.
- Each channel has its own lower environments and production.

**Mesh:** Istio service mesh on all clusters.

**Standard resources per microservice:** Deployment, Service, ConfigMap, HPA, ServiceAccount, VirtualService, DestinationRule.

**On-prem naming**

| Resource | Name |
|---|---|
| Deployment | `appname-{{version}}` |
| Service | `appname` |
| ConfigMap | `appname-cmap` |
| HPA | `appname-{{version}}` |
| VirtualService | `appname-virtualservice` |
| DestinationRule | `appname-destination` |
| ServiceAccount | not stated by owner — discover, then confirm in the clarification loop |

AKS naming was not stated by the owner; discover it (Section 6.4e) rather than assuming the on-prem pattern.

**On-prem blue/green:** custom process; traffic weight between versions is set via VirtualService subsets.

### 6.2 Access model (tiers)

| Tier | What Copilot uses | Scope |
|---|---|---|
| 1 (first) | **GitLab sources of truth** the owner points to: deployment templates, Helm charts/manifest repos, CI templates, Istio config repos, runbooks | Conventions as designed |
| 2 | **Anchor's read-only `anchor-kube` MCP server**, connected to Copilot in VS Code | Non-PCI lower environments (IT, UAT, perf) |
| 3 | **Survey script run by the owner** (`tools/survey/cluster_survey.py`), redacted output handed to Copilot | PCI, preprod, employee, prod; and counts across all 27 clusters |

Why tier 2 uses Anchor's MCP server: same allowlist and redaction Anchor uses, no kubeconfig in Copilot, and Copilot learns the exact tool names and output shapes the skills must reference. If a needed read isn't possible through anchor-kube, record it as a **tool gap** rather than bypassing it.

The owner may also point Copilot to other data Anchor needs (catalog exports, Panorama object naming, DNS/GTM conventions, on-call runbooks). Add each to `docs/environment-survey/sources.md` with what it's authoritative for.

### 6.3 Sampling plan
Don't walk all 27 clusters by hand. Copilot proposes a sample for owner approval: at least one cluster per **platform × channel**, covering IT, UAT and prod tiers. The survey script then runs over all clusters for counts and exceptions only.

### 6.4 What to discover
a. **Cluster inventory:** for each cluster: platform, channel(s), environment(s), PCI flag, site/region, status (`active | migrating | decommissioning`).
b. **Namespace naming rule:** how to parse a namespace into channel / environment / app group, e.g. `apl-digital-secure-banker-services-uat5`. List patterns and exceptions.
c. **Convention conformance:** % of workloads matching the 7-resource set and the naming templates, per platform; exceptions grouped by pattern (not listed individually).
d. **On-prem blue/green mechanics:** how VirtualService subsets → DestinationRule subsets → version labels → `appname-{{version}}` Deployments; how to identify the **live** version (weight), the **idle** version, and **stale** versions left behind; HPA per version; what a normal cutover looks like in the VS (weights 100/0 vs canary steps).
e. **AKS conventions:** the same questions for AKS: naming, blue/green vs rolling, how deployments are applied (Helm, Argo CD, Flux, pipeline `kubectl apply`), ingress path (Istio gateway, App Gateway, internal LB), workload identity.
f. **Labels/annotations** linking a workload to catalog entry, repo, team and version.
g. **Istio:** version and revisions per cluster, injection method, PeerAuthentication mode, `outboundTrafficPolicy`, ingress/egress gateways, Gateway TLS mode distribution, ServiceEntry usage.
h. **Config and secrets:** ConfigMap conventions; Vault sync mechanism (operator, CSI driver, injector) — metadata and status only.
i. **Add-ons:** CRDs/operators installed (cert-manager, Vault operator, policy engines, monitoring agents) with versions.
j. **Migration:** services present on both platforms; how traffic is split between on-prem and AKS (DNS, GTM, F5, other); markers for decommissioning namespaces.
k. **Catalog gaps:** services with no repository mapping (e.g. `usb-dss-accounts` shows "Repository: not reported").

### 6.5 Clarification loop
After each discovery batch, Copilot writes `docs/environment-survey/questions-<n>.md` and stops:
- At most 10 questions per batch.
- Each question includes: what was observed (counts, 1–2 redacted examples), Copilot's proposed interpretation, and answer options.
- The owner answers inline. Copilot updates the model and tags each fact `owner_stated | observed | confirmed`.

Examples of the kind of questions expected:
1. "Environment list has 'employee'. Observed namespaces end in `-emp1`, `-emp2`. Is that the employee environment, and is it prod-tier data?"
2. "Observed 41 VirtualServices with 3+ subsets. Are older subsets expected leftovers, or should Anchor flag them?"
3. "AKS workloads use `app.kubernetes.io/instance` and Helm labels, not `appname-{{version}}`. Is AKS rolling update rather than blue/green?"
4. "Banker channel appears on clusters X and Y. Is X lower-env and Y prod, or are they split by site?"

### 6.6 Outputs
- `config/environment/environment-model.yaml` — **machine-readable**: clusters, namespace parsing rules → channel/environment, platform, PCI flag, status. Consumed by code (target resolver hints, family router, migration answers). Additive: the resolver uses it first for disambiguation hints, not as hard filters.
- `config/environment/conventions/{onprem,aks}.yaml` — naming templates, required resource set, blue/green rules.
- `skills/env-conventions/SKILL.md` — how to apply the model: find the live version, map Deployment ↔ Service ↔ VS ↔ DR, migration caveats, decommissioning namespaces.
- `docs/environment-survey/summary.md` and redacted per-cluster JSON.
- **Rule:** skills never list specific clusters or services; those live only in the model file, which the survey regenerates.
- **Drift check:** a command re-runs the conformance checks against the model and reports drift, so conventions changing in the clusters don't silently make skills wrong.

### 6.7 Survey script requirements
- get/list only; refuses any other verb.
- Never reads Secret data; for Helm release secrets, reads labels only (`owner=helm`, `name`, `status`, `version`).
- Aggregates and patterns, not full dumps. Hashes IPs and credential-looking annotation values.
- Test proves no Secret data is read.

**Done when:** model and conventions confirmed by the owner, survey run on all clusters (counts) and the approved sample (detail), drift check works.

---

## 7. Phase 4 — Skills (solves P3)

### 7.1 Two layers
- **Generic skills** — how Kubernetes, Istio, Helm and AKS behave. Portable, no names from our environment.
- **Environment overlay** — `env-conventions` plus the model files. Generic steps say "locate the live version and its DestinationRule per env-conventions" instead of hard-coding names.

### 7.2 Generic skill catalog

**Kubernetes**
- `k8s-pod-restarts-crashloop` — termination reason and exit code, OOMKilled, probe failures, previous-container logs, cumulative restart counts, expired events.
- `k8s-pending-scheduling` — resources, taints/tolerations, affinity, PVC binding, quotas.
- `k8s-image-pull` — tag, registry auth, network path to registry.
- `k8s-probes-readiness` — readiness vs liveness vs startup, endpoints not ready.
- `k8s-rollout-stuck` — progress deadline, failing new ReplicaSet, maxUnavailable.
- `k8s-hpa-scaling` — metrics unavailable, min/max limits, per-version HPAs.
- `k8s-service-endpoints-dns` — selector mismatch, no endpoints, CoreDNS.
- `k8s-node-pressure-evictions`.
- `k8s-config-secrets-sync` — ConfigMap change not picked up, Vault sync status (metadata only).

**Istio**
- `istio-503-response-flags` — UH, UF, URX, NR, UC, UO, DC, UT and what each means; needs access logs (state the gap while Kibana/Datadog are disconnected).
- `istio-routing-config` — VS host/gateway binding, subset missing from DR, weights not summing to 100, multiple VS for the same host.
- `istio-blue-green-traffic` — subset weights, live vs idle version, cutover and rollback checks (uses the overlay).
- `istio-mtls-peerauth` — STRICT vs PERMISSIVE, DR TLS settings mismatch.
- `istio-sidecar-injection` — missing sidecar, revision/version skew, startup ordering.
- `exposure-and-tls` — Section 5.4.
- `istio-egress` — `REGISTRY_ONLY`, ServiceEntry, egress gateway, then Panorama and DNS hop by hop.

**Helm** (only if discovery confirms Helm is used)
- `helm-release-failed` — failed / stuck `pending-*` releases, hook failures, ownership annotation conflicts, revision history from metadata.
- `helm-values-drift` — Git values vs deployed state.
- Anchor has no Helm tool today: record as a tool gap; read release status from secret labels only.

**AKS / Azure** (only where discovery shows use)
- `aks-nodepool-upgrade`, `aks-networking-private-dns`, `aks-workload-identity`, `aks-appgateway`.

**Cross-cutting**
- `change-correlation` — what changed recently: deployed SHA, ConfigMap, VS weights, Helm revision, cluster/Istio upgrade.
- `cert-expiry`.

### 7.3 Order
Rank by Phase 1 question frequency and Phase 5 gaps. Suggested first wave: `env-conventions`, `k8s-pod-restarts-crashloop`, `istio-503-response-flags`, `istio-routing-config` + `istio-blue-green-traffic`, `exposure-and-tls`, `istio-egress`.

### 7.4 Skill template
```markdown
---
name: <skill-name>
layer: generic | environment
family: <family id>
platforms: [onprem, aks]
triggers: <concrete symptoms/phrases>
required_tools: [...]
tool_gaps: [...]          # steps we can't do yet, and why
---
## When to use
## Steps (ordered; exact Anchor tool names and arguments)
## How to tell look-alike causes apart
## What good vs bad looks like (short redacted output snippets)
## Common false leads
## What counts as established / answered
## If a tool is unavailable
## Environment notes (pointer to env-conventions; on-prem vs AKS differences)
```
1–2 pages each; reference material in `skills/<name>/reference/*.md`, loaded on demand.

### 7.5 Content sources
- Behavior details: official Kubernetes, Istio, Helm and AKS docs, **matched to the versions found in discovery** (defaults differ by version; note the version in the skill).
- False leads and look-alikes: our past incidents from the question bank and ServiceNow.

### 7.6 Validation
- Startup check: every tool named in a skill exists in the discovered menu.
- Each skill has at least 3 replay cases from the question bank.
- Owner reviews the first-wave skills before merge.

**Done when:** first wave merged, tool check passes, replay cases pass in native mode, no planner-mode regression.

---

## 8. Phase 5 — Coverage run & gap map

1. Run the question bank through Anchor (replay where cassettes exist, live read-only otherwise, rate-limited).
2. Label results: `correct · wrong_route · missing_tool · missing_playbook · wrong_answer · unverifiable`.
3. Report `evals/reports/coverage-<date>.md`: pass rate per family, channel and platform; top failure reasons; ranked list of next skills/tools.
4. Re-run after every skill, routing or environment-model change; this is the regression gate.

---

## 9. Out of scope (for now)
- Connecting Kibana/Datadog (playbooks handle their absence).
- Typed tool errors.
- Any write action or remediation.
- A topology/dependency-map service.

## 10. Acceptance summary

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Discovery report | Owner approval |
| 1 | Question bank + 👎 hook | Counts reported, no secrets in output |
| 2 | Families + router + capability check | `exposure_tls` replay passes, both modes |
| 3 | Environment model, conventions, survey, drift check | Owner confirms model; no Secret reads |
| 4 | Generic + environment skills (first wave) | Tool check passes, 3 cases per skill pass |
| 5 | Coverage report | Ranked gap list delivered |
