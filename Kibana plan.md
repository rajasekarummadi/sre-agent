# Kibana plan

Logs move to Kibana: history, search, error onset and access logs. anchor-kube keeps live cluster state plus one narrow fallback for crash output Kibana may miss. Each MCP server owns one kind of data, so the agent never has two tools competing for the same question. Start after the rerun 3 report.

## Server roles

One owner per kind of data. Tool descriptions and skills point the agent to the owner first.

| Server | Owns | Doesn't own |
| --- | --- | --- |
| anchor-kube | Live cluster state: pods, readiness, restarts, termination reasons, recent events, workload and Istio config (Deployment, Service, HPA, VirtualService, DestinationRule, Gateway), rollouts, DNS/TLS probes. The last crashed container's output, as a fallback only | Log search or log history |
| anchor-kibana | Log history and search: error signatures, onset time, rates, affected pods, trace and correlation IDs, Istio/Envoy access logs (status codes, response flags) | Live pod state, configuration |
| anchor-gitlab | Code, config files, pipelines, deployed commit, library source | Runtime state |
| anchor-now | Incidents and change requests | Runtime state |
| anchor-panorama | Firewall rules and commits | Runtime state |
| Service catalog | Ownership, environment and cluster mapping | Live state |

## Logs: Kibana first

Kibana answers every log question. Keep anchor-kube's pod-log tool, but only as a fallback: crash-loop RCAs depend on the previous container's last lines, which Kibana can miss.

- Any log question, or log step in an investigation, goes to Kibana first.
- Pod logs are used only when the last crashed container's output is missing from Kibana for the window (ingestion lag, or the container died before shipping), or when the environment doesn't ship to Kibana.
- The answer says which source each log line came from.
- Every log evidence item records source, query, time window, and a link that opens the same query in Kibana Discover, so engineers can check it themselves.

Kibana queries use the same target as every other tool: the cluster and namespace that catalog-first discovery found, with environment names through the shared normalizer (uat1 = uat01 = UAT-001).

## Answers needed from you

These decide how the tools map services to logs. Most are quick to find in Kibana itself.

- [ ] Kibana version, and whether the server calls the Kibana API or Elasticsearch search through Kibana
- [ ] Index patterns or data views per environment, on-prem and AKS. Do AKS clusters ship to the same Kibana?
- [ ] Field names for namespace, pod, container, service, level, message, and trace or correlation ID
- [ ] Are Istio/Envoy access logs indexed, and in which index?
- [ ] Retention per environment and typical ingestion lag
- [ ] API key scope: read-only, limited to the needed indices; stored in .anchor-local/.env
- [ ] Policy: may Anchor read production logs? (security sign-off)
- [ ] Query limits the Kibana owners expect on the shared cluster
- [ ] Path to the Kibana MCP server repo and skill file

## Tool contract

Adapt names to what the existing server offers; what matters is bounded, structured output. The model never sees a raw log dump.

| Tool | Input | Returns |
| --- | --- | --- |
| logs\_search | Service, or namespace and pod; environment; time window; query; level | Counts by level, top error signatures (normalized message templates) with counts, first and last seen, up to 5 redacted samples, Discover link |
| logs\_error\_onset | Service, environment, time window | Error counts per time bucket, first error time, spike start |
| logs\_signature\_detail | Signature, time window | Samples, affected pods and versions, distribution over time |
| access\_logs | Service or host, time window | Status codes, Envoy response flags (UH, UF, URX, NR, …), upstream, latency percentiles |
| logs\_trace | Trace or correlation ID | Matching lines across services, in time order |

logs\_error\_onset also anchors the time window for the change timeline (next item, U5).

## Safety and guardrails

Kibana is shared with other teams and holds customer data, so the limits matter as much as the tools.

- **Read-only:** no saved objects, index or settings writes; tool allowlist enforced in code.
- **Redaction before the model:** card numbers (Luhn check), account numbers, tokens and JWTs, emails, phone numbers.
- **Shared-cluster limits:** maximum window (24 h for Ask, 7 days for Investigate), result size caps, query timeout, no leading wildcards, rate limit.
- **Environments:** index allowlist per environment from clusters.yaml; production only if the policy answer allows it.
- **Audit:** every query logged with user, thread, index and window.
- **Degraded mode:** if Kibana is down or access is denied, say so and use pod logs where allowed; never crash.
- **Time:** UTC throughout; say so when a window is older than retention.

## Implementation steps

1. **Review, report only:** the server's tools (read-only or not), its config, and the skill file's tool names and overlaps with anchor-kube.
2. **Add anchor-kibana to compose** with a health check; API key from .anchor-local/.env only; startup tool-name check.
3. **Tools:** bounded outputs per the contract, redaction, shared-cluster limits.
4. **Server roles in anchor-main:** tool descriptions, the pod-log fallback rule, source labels on evidence, Discover links in the evidence panel.
5. **Skills:** convert the Kibana skill to the standard template; crashloop and Istio 503 skills use Kibana first.
6. **Tests:** golden tests with recorded Kibana responses; a Kibana-down test; 10 log questions added to the broad set; a smoke\_live step.
7. **Flag:** ANCHOR\_KIBANA, default off. It is the second temporary flag; remove it by Nov 25.
8. **Measure:** rerun the broad set and compare.

## Acceptance

- [ ] Golden set green with ANCHOR\_KIBANA on and off
- [ ] "When did errors start for X in uat5?" is answered from Kibana with the onset time and a Discover link
- [ ] The crash-loop scenario still works and shows the source of each log line
- [ ] An Istio 503 question shows response flags from access logs (if they are indexed)
- [ ] No unredacted sensitive data in evidence (tested with a seeded fake card number)
- [ ] Kibana down gives a clear message, not a crash
- [ ] Broad-set pass rate equal or better than before, with the log questions added

## Prompt for Copilot (U4)

Opus. Send in a second VS Code window opened on the Kibana worktree, after filling in the answers above. Steps 1–3 run alongside S1; steps 4–8 after S1 is merged. Replace the path placeholder first.

```text
U4: Kibana integration. Work in ~/Git/anchor-main-v2-kibana, branch feature/kibana.
Until I say S1 is merged: no deploys, no anchor-kube restarts, no skill edits
(S1 owns the skills; expose the logs tools only). The plan is in designdoc2/Kibana plan.md; rules in .github/copilot-instructions.md.
The Kibana MCP server and its skill file are in <path to repo>. Read them
first.

Report first, no changes:
1. Tools the server exposes; mark read-only vs write; config it needs.
2. The skill file: tools it names; overlaps with anchor-kube pod logs.
3. Gaps against the plan's tool contract and guardrails.

Then, after my go-ahead, implement steps 2-8 of the plan:
- anchor-kibana in compose with a health check; API key from
  .anchor-local/.env only, never logged.
- Bounded tools per the contract; redaction; shared-cluster limits.
- Server roles: logs go to Kibana first; anchor-kube pod logs only as the
  fallback in the plan; every log evidence item shows source, query,
  window and a Kibana Discover link.
- Skills: convert the Kibana skill to our template; crashloop and Istio 503
  skills use Kibana first.
- Tests: golden (recorded Kibana responses), Kibana-down, 10 log questions
  in the broad set, a smoke_live step.
- Behind ANCHOR_KIBANA, default off.
Full suite green before every commit.
```
