# Demo script

A 25-minute demo for management: Anchor as an agent harness of its own, not a wrapper around Copilot. Live where it is safe, recorded replays where live data has moved on, and every replay labelled as one.

## Run of show

25 minutes, then 10 for questions. Start scenario 2's live investigation in a second tab at minute 3, so it is finished when you reach it.

| Minutes | Segment | Shown in | Mode |
| --- | --- | --- | --- |
| 0–2 | The problem | Slides | — |
| 2–5 | A harness, not a wrapper | Architecture tab | — |
| 5–9 | Scenario 1: find and follow up | Console | Live |
| 9–14 | Scenario 2: investigation with review | Console | Live, or replay |
| 14–17 | Scenario 3: root cause in config | Console | Replay |
| 17–19 | Scenario 4: answer, don't investigate | Console | Live |
| 19–21 | Engineering rigour: scorecard, telemetry, read-only | Scorecard page | — |
| 21–23 | Same harness, better model | Slide | — |
| 23–25 | The ask | Slide | — |
| 25–35 | Questions | — | — |

## Scenarios

These are proposals; confirm or swap them by November 6 (Plan tab). Each scenario shows one harness strength.

**Scenario 1: find and follow up (live).** Shows: search instead of asking, and memory within a thread.

- Type: "Are the usb-dss-accounts pods healthy in banker uat5?"
- Expected: routed to a lookup; target found by search with no question; pods, readiness and restart counts.
- Then type: "What caused the restarts?"
- Expected: an investigation starts with the same target; the first tool calls are diagnostics.
- Point at: the routing line in the live feed, "target resolved by search", the investigation network.
- On November 30, if this service has no recent restarts, swap in one that does.

**Scenario 2: investigation with review (live, or labelled replay).** Shows: evidence, the reviewer, and honest uncertainty.

- Question: the follow-up from scenario 1, or "Why are the usb-dss-accounts pods in banker uat5 restarting?"
- Expected: exit code 1 from crash diagnostics; `PolicyNotFoundException` in the previous container's logs; deployed commit resolved from pipeline 16700595 and source read at that commit; reviewer flags a claim and the agent revises it; status Probable, with the open item under "To confirm".
- Point at: an evidence ID opening its raw result, the deployed-commit line, the reviewer and revision lines, the reason next to "Probable".

**Scenario 3: root cause in config (replay).** Shows: a fully established cause, traced into code.

- Run: bbds-grphqldep, regenerated on the current build (prompt W3-2).
- Expected: Established. The `it` Spring profile sets the Hibernate dialect to `SQLServer2008Dialect` at deployed commit e8b034c; that class is missing from the packaged Hibernate, so the app fails at startup with `ClassNotFoundException`, exits with code 1 and goes into CrashLoopBackOff. OOM is ruled out with evidence. Fix: use `SQLServerDialect` or remove the property.
- Point at: the cause in config at the exact deployed commit, the ruled-out OOM, the fix.

**Scenario 4: answer, don't investigate (live).** Shows: the router choosing the cheap path.

- Type one of: "What changed in the last usb-dss-accounts deploy in uat5?" or "Where does usb-dss-zero-balance-accnts run?"
- Expected: a direct answer from pipeline or workload data in under a minute; no investigation started.
- Point at: the routing decision and the speed.

## Talk track

Plain words, one short block per segment. Replace the bracketed parts with your own numbers.

**The problem.** We run 700+ microservices across 18 on-prem and 9 AKS clusters, for consumer, partner, banker and branch channels. When a pod restarts, an engineer moves between Kubernetes, GitLab, ServiceNow and Panorama to find out why. That typically takes \[your typical time\], and it needs someone who knows where to look.

**A harness, not a wrapper.** Anchor is our own agent harness. The model is one part of it. The harness decides what it may touch (read-only, enforced in code), what counts as evidence, when an independent reviewer checks a claim, and how the result is labelled. It runs inside our network, connects to our catalog, Kubernetes, GitLab, ServiceNow and Panorama, and every claim traces back to evidence.

**Scenario 1.** I ask the way a developer would, with a shorthand name and no cluster. Anchor finds the service itself, then keeps that context when I ask a follow-up.

**Scenario 2.** Here it investigates: crash diagnostics, logs, then the code at the exact commit that is deployed. Watch the reviewer: it challenges a claim, and the agent goes back and fixes it. Where it can't prove something, it says "probable" and lists what to confirm. It doesn't guess.

**Scenario 3.** This one is fully established: the cause was one config setting in one Spring profile, at the deployed commit, with the fix.

**Scenario 4.** Not every question needs an investigation. A factual question gets a direct answer in seconds.

**Engineering rigour.** Every change runs against a replay suite of real incidents before it ships. We track tokens and time per run, and the harness enforces budgets.

**Same harness, better model.** Everything you saw runs on GPT-5.1. On the same \[10\] questions inside the same harness, a frontier model scored \[X\] against \[Y\], and finished in \[time\] instead of \[time\].

**Close.** The harness is ours and already works. A better model, a pilot and a few more connections would make it a daily tool.

## The ask

One slide, in priority order. Fill in the numbers from the comparison.

1. **A frontier model on Azure** for Anchor's investigation loop (GPT-6.x on Azure OpenAI, or Claude through Azure AI Foundry), plus the Responses API on the APIM gateway.
2. **A pilot:** one or two teams for 4–6 weeks, measuring time to root cause against today.
3. **Read access for Anchor's tools** to Kibana, Datadog and the Artifactory registry.
4. **Time:** \[what you need, e.g. a share of your time or one more engineer\].
5. **A security review path,** including per-user access controls before wider rollout.

## Questions to prepare for

| Question | Short answer |
| --- | --- |
| Is it safe near production and PCI systems? | It is read-only by design: the allowlist is enforced in code and no write tools exist. It never reads Secret values, and it runs inside our network. |
| How do we know it's right? | Every claim cites evidence you can open. An independent reviewer checks the draft. Code assigns the status label by rule. A replay suite of real incidents gates every change. |
| What happens when it's wrong or unsure? | It says "probable" or "unknown" and lists what to confirm. It never changes anything on its own. |
| Why not just use GitHub Copilot? | Copilot helps one developer in an editor. Anchor is a service: it answers in a shared console and on ServiceNow incidents, uses our catalog, ServiceNow and Panorama, and runs under controls we define and measure. The model is swappable. |
| What does a run cost? | \[median tokens and cost per investigation from the scorecard\]. |
| What if we change model vendors? | The model is set per step in config; the harness stays the same. |
| Does data leave the bank? | Model calls go through our Azure gateway under the bank's existing agreement. |
| How long to production? | A pilot can start once a model is approved; per-user access controls come before wider rollout. |

## Demo-day checklist and backup plan

**Monday, November 30**

- [ ] Image from tag `demo-2026-12-01` is running; all MCP servers show healthy
- [ ] Scenario 1 and 4 services still exist in UAT; scenario 1 has recent restarts, or a replacement is chosen
- [ ] Replay bundles for scenarios 2 and 3 load and play
- [ ] Backup recordings saved and opened in tabs
- [ ] Console list cleared of test threads and stale investigations

**Morning of December 1**

- [ ] VPN connected; one test question answered through the Azure gateway
- [ ] Browser zoom at 125%, notifications off, unrelated tabs closed
- [ ] Second tab ready to start scenario 2 at minute 3

**If something goes wrong**

- A live call hangs for more than 2 minutes: say so, and switch to that scenario's recording.
- The network is down: run every scenario in replay mode.
- Anchor is wrong or unsure live: point at the status label and "To confirm". Admitting uncertainty is part of the design.
