# Copilot prompts

Paste these in order, one at a time, in the owner's Copilot chat (Team section on the Plan tab), on a branch off `feature/agent-harness-redesign`. Wait for the report, tick the checks under each prompt, then send the next. Use Opus for W1-1, W2-1, W2-3, W3-1 and W3-2, and Sonnet for the rest.

## Now

**N1: decisions, status and the deployed-commit resolver.** Send when Copilot finishes its current task.

```text
We are now working to a management demo on Dec 1. From here on, a change
goes in only if a demo scenario needs it.

Decisions on your proposal:
1. Yes, add search_projects(query, group) and list_tags(project, search) to
   anchor-gitlab, read-only, bounded output. Leave them uncommitted in that
   repo as before and tell me what to deploy.
2. Library location: I'll find where dss-parent-pom 4.1.38 and
   usb-dss-authorization 4.1.x live. Until then, a miss is a precise blocker,
   never a fallback to the branch head.
3. Resolver calls may sit outside the agent's 20-call cap, but they count in
   the run's total calls and tokens.
4. Confirmed: no catalog write-back.

First, update docs/harness-redesign-status.md: which fixes from my ba3436ed
message are merged (report dedupe, receipt mapping, incident timing, single
status label, reviewer revision round, events filter, likely-fix cleanup,
token usage), and the full test-suite result via the test entry point.
Then implement item 1 (deployed SHA resolver) and item 3 (cross-checks).
Replay 1667f753 in both modes and report the ref used for every source read.
```

Check when it reports back:

- [ ] Status doc lists what is merged and what isn't
- [ ] Full test suite green
- [ ] Replay of 1667f753 reads source at 9fbc51d0, with the method recorded as evidence

## Week 1

**W1-1: find the target by searching.**

```text
Demo plan, week 1: Anchor must find the target by searching, not by asking.
Investigation 8e4b7a3d ("usb-dss-zero-balance-accnts service in banker uat5
namespace has container restart") made one catalog call, asked "which
Kubernetes cluster (name or context)", then ended with "Target clarification
remains unresolved ... provide the exact target in a new request". Zero
Kubernetes calls.

1. Report first, no changes: the exact path for that run - catalog terms and
   result, why it went to NEEDS INPUT, how my answer was parsed, why it ended.
2. find_workloads(name_hint, environment?, channel?) in anchor-kube,
   read-only: fuzzy match (tokens, abbreviations such as accnts/accounts,
   version suffixes) against Deployment and Service names in allowed
   namespaces of the clusters for that environment. Returns up to 10 ranked
   candidates {cluster, namespace, deployment, service, match_reason}.
3. config/environment/clusters.yaml: create the template (cluster -> platform
   onprem|aks, environments, channels, pci, status; namespace patterns ->
   channel and environment, e.g. *-banker-*-uat5) and a loader that validates
   it. I'll fill it in.
4. Resolution order: catalog -> clusters.yaml -> find_workloads.
   One candidate: proceed and state the resolved target and how it was found.
   2-5: one question with clickable candidate buttons in the console, with
   provenance. 0: say what was searched and suggest close names.
   Never ask for a cluster or context name in free text.
5. No dead ends: never "provide the exact target in a new request"; the
   investigation stays resumable in the same thread.
6. One status at a time (8e4b7a3d showed complete, NEEDS INPUT and
   unresolved together).
7. Replays in both modes: 8e4b7a3d, 45a7ca8e and 5 messy variants
   (abbreviated name, channel + environment words, no environment, a name
   with two matches, a name with no match).
Proposal for 2-4 first, then implement. Full suite green before push.
```

Check when it reports back:

- [ ] 8e4b7a3d replay resolves to one target with zero questions; first calls are diagnostics
- [ ] The two-match variant shows buttons, not a free-text question
- [ ] The no-match variant says what was searched
- [ ] The 45a7ca8e follow-up keeps the target

**W1-2: demo scenarios in the replay suite.** Send after you fill in the scenarios on the Demo script tab.

```text
Add the four demo scenarios (questions below) to the replay suite under
evals/cases/demo/, recorded from live UAT runs now so they can be replayed
later even if UAT changes. Run each once in native mode and report: route,
target found, questions asked, status label, time, tokens (cached and
uncached), and anything wrong on screen. No code changes in this prompt.

<paste the four scenario questions>
```

- [ ] Four cases recorded
- [ ] Timing per scenario known; anything over 4 minutes flagged

## Week 2

**W2-1: router and escalation.**

```text
Demo plan, week 2: routing and interactivity.
1. Router: keep fixed rules for ServiceNow incidents and webhooks, a pending
   NEEDS INPUT question, and the Investigate button. Everything else: one
   structured GPT-5.1 call at low effort, with thread state as input,
   returning {route: answer|lookup|investigate, family, identifiers,
   new_target, confidence, reason}. On failure or confidence below 0.6:
   route answer, family other, logged.
2. Escalation both ways: an answer or lookup that finds a real failure (for
   example restarts with exit code other than 0) offers Investigate with the
   target attached; an investigation whose question turns out to be factual
   answers and stops.
3. A "Dig deeper" button on answers starts an investigation with the same
   target.
4. Log every routing decision with its reason; show it in the live feed as
   one line.
5. Replays, both modes: "Are the usb-dss-accounts pods healthy in banker
   uat5?" -> lookup, no RCA; then "What caused the restarts?" in the same
   thread -> investigation with the same target; one factual question ->
   answer.
Proposal first. Full suite green before push.
```

- [ ] Status question answered without starting an investigation
- [ ] Follow-up starts an investigation with the inherited target
- [ ] Routing line visible in the live feed

**W2-2: side questions and resume.**

```text
While an investigation waits for input, classify each new message first:
- answer to the pending question -> resume the investigation;
- side question -> answer it, keep the investigation pending, and remind the
  user what is still needed;
- new request -> handle it normally; the pending investigation stays
  resumable.
Resume from the Postgres checkpoint, not the in-worker state dict. If the
checkpoint is missing, show a recovery message with the known target instead
of starting over. Tests in both modes, including a simulated worker restart.
```

- [ ] Side question answered while the investigation still waits
- [ ] Worker restart test passes

**W2-3: reviewer and revision, visible.**

```text
Make the reviewer -> revision step real and visible (if part of it is already
merged, verify it and add only what's missing):
1. After the reviewer runs, if budget remains and it raised concrete,
   checkable requests (cite X, read Y), run one revision round: the agent
   handles them with tool calls, then the draft is checked once more.
2. Live feed lines: "Reviewer flagged: <one line>" -> "Revising: <action>" ->
   "Re-check: passed" or "still open".
3. The report lists only what is still open after revision, under
   "To confirm".
4. One round at most, within the existing budget reserve.
Replay ba3436ed: the "cite crash diagnostics for the exit/restart claim"
request should be resolved in the revision.
```

- [ ] Three revision lines appear in the feed
- [ ] The resolved request no longer shows under "To confirm"

**W2-4: library source.** Only if you found the location; fill in the paths.

```text
Library location: dss-parent-pom 4.1.38 is at <path>; usb-dss-authorization
4.1.x is at <path>; tags look like <pattern>. Implement item 2 of your
proposal with these as the first candidates. Replay 1667f753: the policy
classes should be found at the matching tag and recorded as
"defined in <library>@<version>", or a precise blocker.
```

- [ ] Classes found at the matching tag, or a blocker that names what was tried

## Week 3

**W3-1: make the harness visible.**

```text
Demo plan, week 3: make the harness visible in the console. UI and read-only
changes only; no loop changes.
1. Architecture tab: a diagram of the native loop - intake -> router ->
   agent <-> tools -> end-of-run checks -> reviewer -> revision -> report -
   with what each part enforces (read-only allowlist, budgets, evidence IDs,
   status rule). During a live run, highlight the current stage.
2. Evidence drill-down: clicking an evidence ID anywhere in the report opens
   the raw evidence (tool, arguments, time, bounded result) in a side panel.
3. Status reason: next to the status label, one line on why, e.g.
   "Probable: mechanism evidenced; underlying cause still open".
4. Scorecard page: reads evals/reports/ (replay suite and parity results) and
   shows pass rate, tokens and time per scenario.
5. Token panel: cached vs uncached input per stage.
Describe each view first, then implement.
```

- [ ] Each view works on a real run
- [ ] Clicking an evidence ID opens the raw result

**W3-2: demo replay mode.**

```text
Add a demo replay mode: play back a recorded investigation in the console
from its stored events and evidence, at real speed or 4x, with a visible
badge "Replay of <id>, recorded <date>". No model or tool calls during
replay. Reuse the existing event store and timeline. Add a CLI to export an
investigation as a replay bundle.
Then regenerate two demo runs on the current build from their recorded tool
results: the usb-dss-accounts restarts (1667f753 or its latest rerun) and
bbds-grphqldep (33014af6). The bbds-grphqldep report should now come out as
established. Export both as replay bundles.
```

- [ ] Both bundles play back with the Replay badge
- [ ] bbds-grphqldep shows established, with the Hibernate dialect cause

**W3-3: parity set and model override.**

```text
Model comparison for the demo:
1. evals/parity/: 20 cases from our runs and the demo scenarios (8e4b7a3d,
   45a7ca8e, 1667f753, ba3436ed, 33014af6, plus status, deploy and restart
   questions with shorthand names and follow-ups). Fields: expected_route,
   expected_target, must_inspect, expected_answer (I'll review).
2. Scoring: target_found, questions_asked, dead_end, route_correct,
   deployed_sha_used, answer score (LLM judge against expected_answer),
   turns, tokens (cached and uncached), time.
3. Model override for the native agent node only (models.yaml override per
   run); router, intake and report stay on GPT-5.1. Hard caps per run and per
   batch; stop when reached. I'll provide the gateway endpoint and key at run
   time; never store them in the repo or logs.
4. Run all 20 on GPT-5.1 now and write evals/reports/parity-gpt51.md. I'll
   run the frontier batch myself (20 questions x 3 runs).
Proposal first.
```

- [ ] Baseline report written
- [ ] Override and caps tested with a dry run that makes no model calls

## Week 4

**W4-1: reliability runs.** Monday, November 23.

```text
Demo plan, week 4: reliability only. Run each demo scenario 3 times (live
where marked, replay otherwise) and report a table: scenario, run, status
label, target found, questions asked, time, tokens, anything wrong on
screen. Fix only issues that break a scenario; list everything else for after
the demo. No other changes this week.
```

- [ ] Every scenario passes 3 of 3
- [ ] Live scenarios finish within 4 minutes

**W4-2: freeze.** Wednesday, November 25, after the dry run fixes.

```text
Freeze for the Dec 1 demo:
1. Full test suite and replay suite green via the test entry point.
2. Tag the commit demo-2026-12-01 on feature/agent-harness-redesign; build
   the anchor-main image from that tag. Write docs/demo-runbook.md with the
   image tag, the previous image for rollback, and the exact deploy and
   rollback commands (override files in .anchor-local/, not the Copilot
   session folder).
3. Mark stale investigations as failed and clear test threads from the
   console list.
After this, no changes unless I ask.
```

- [ ] Tag created and image deployed from it
- [ ] Rollback command tested once
- [ ] Console list is clean
