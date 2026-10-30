# Anchor Demo Plan

Oct 30, 2026 · @Rajasekar Ummadi

Demo Anchor to management on Dec 1, 2026: an agent harness of its own, shown live, with the numbers for a frontier-model request. Four weeks of scoped work get it there; anything not on this plan waits until after the demo. Prompts to paste are in Copilot prompts, and the run of show is in Demo script.

## Key dates

The demo is on Tuesday, December 1, after Thanksgiving week, leaving Monday, November 30 as a buffer. Friday, November 13 is the go/no-go point for keeping that date.

| Date | Milestone |
| --- | --- |
| Oct 30, 2026 | Plan agreed; answer Copilot's open decisions |
| Nov 2, 2026 | Week 1 starts: finding the target |
| Nov 3, 2026 | `clusters.yaml` filled in (you) |
| Nov 6, 2026 | Week 1 check; scenarios chosen; demo invite sent |
| Nov 13, 2026 | Week 2 check; go/no-go for December 1 |
| Nov 20, 2026 | Week 3 check; model comparison numbers in hand |
| Nov 24, 2026 | Dry run with one friendly manager |
| Nov 25, 2026 | Code freeze: release tag, image built from the tag |
| Nov 30, 2026 | Final environment check |
| Dec 1, 2026 | Demo |

No evals on Tuesday, November 17, 8:00–11:59 PM CT: GitLab is read-only for its v19.2 upgrade. No work is planned on Thanksgiving, November 26–27.

## Demo-ready

The demo goes ahead when every box below is ticked. This list replaces "waiting for the final product".

- [ ] Four scenarios pass 3 runs out of 3 in UAT, live or as a labelled replay
- [ ] No free-text "which cluster?" questions and no dead ends
- [ ] A follow-up in the same thread keeps the target
- [ ] Live scenarios finish within 4 minutes
- [ ] Each finding appears once, with one status label and a plain reason
- [ ] The reviewer flags something and the agent revises it, visibly in the live feed
- [ ] The report shows the source read at the deployed commit
- [ ] Scorecard page and model comparison numbers are ready
- [ ] Full test suite green; image built from a tagged commit
- [ ] Backup recording for every scenario

## Week-by-week plan

Each week ends with a check on Friday. Prompt codes (N1, W1-1, …) match the Copilot prompts tab; the Team section says who owns each one.

**Now, October 30 – November 1: close out in-flight work**

| Task | Who | Done when |
| --- | --- | --- |
| Answer Copilot's open decisions; confirm which fixes are merged | You → Copilot (N1) | Status doc lists merged fixes; full suite green |
| Deployed-commit resolver from the pipeline ID | Copilot (N1) | Replay of 1667f753 reads source at 9fbc51d0 |

**Week 1, November 2–6: find the target by searching**

| Task | Who | Done when |
| --- | --- | --- |
| Fill `clusters.yaml` for the 27 clusters | You | File committed; loader validates it |
| Workload search, resolution order, clickable choices, no dead ends | Copilot (W1-1) | 8e4b7a3d replay resolves with zero questions |
| Pick the four scenarios; check each one reproduces in UAT | You | Scenarios filled in on the Demo script tab |
| Add the scenarios to the replay suite; first timings | Copilot (W1-2) | Time, tokens and status reported per scenario |
| Book the demo for December 1 | You | Invite sent |

**Week 2, November 9–13: interactivity**

| Task | Who | Done when |
| --- | --- | --- |
| Router, escalation both ways, "Dig deeper" | Copilot (W2-1) | Status question gets a lookup; follow-up starts an investigation with the same target |
| Side questions and resume from checkpoint | Copilot (W2-2) | A side question is answered while an investigation waits |
| Reviewer → revision round, visible in the feed | Copilot (W2-3) | Revision lines appear on the ba3436ed replay |
| Library source, only if you found its location | You, then Copilot (W2-4) | Policy classes found at the matching tag, or a precise blocker |
| Go/no-go | You | On track for December 1, or move the date now |

**Week 3, November 16–20: show the harness and the numbers**

| Task | Who | Done when |
| --- | --- | --- |
| Architecture view, evidence drill-down, status reason, scorecard page | Copilot (W3-1) | Each view works on a real run |
| Demo replay mode; regenerate scenarios 2 and 3 on the current build | Copilot (W3-2) | Both play back with a Replay badge |
| Parity set and per-run model override | Copilot (W3-3) | GPT-5.1 baseline report written |
| Frontier-model comparison: 20 questions × 3 runs, within its budget | You | Comparison numbers in hand |
| Draft 6–8 slides | You | Slides ready for the dry run |

**Week 4, November 23–25: reliability and rehearsal**

| Task | Who | Done when |
| --- | --- | --- |
| Reliability runs; fix only what breaks a scenario | Copilot (W4-1) | Every scenario passes 3 of 3 |
| Record a backup video per scenario | You | Four recordings saved |
| Dry run with one friendly manager | You | Feedback noted; fixes take half a day at most |
| Freeze: tag, image from tag, runbook with rollback | Copilot (W4-2) | Tag `demo-2026-12-01` deployed; rollback command tested |

## Your tasks

These need you; Copilot can't do them. They are the most likely cause of a slip, so each has a date.

- [ ] Send Copilot prompt N1 — Oct 30, 2026
- [ ] Fill `clusters.yaml`: 18 on-prem and 9 AKS clusters with platform, environments, channels and PCI flag — Nov 3, 2026
- [ ] Pick the four scenarios and check each reproduces in UAT — Nov 6, 2026
- [ ] Book the demo for December 1 (25 minutes plus 10 for questions) — Nov 6, 2026
- [ ] Find where `dss-parent-pom` 4.1.38 and `usb-dss-authorization` 4.1.x live in GitLab — Nov 9, 2026
- [ ] Go/no-go call on December 1; ask a friendly manager for the November 24 dry run — Nov 13, 2026
- [ ] Gateway access ready for the model comparison, capped at its budget — Nov 16, 2026
- [ ] Run the comparison; draft 6–8 slides — Nov 20, 2026
- [ ] Record backup videos — Nov 23, 2026
- [ ] Dry run — Nov 24, 2026
- [ ] Final environment check from the Demo script tab — Nov 30, 2026

## Team

Four people work in parallel, each in a separate area so changes don't collide. You own integration: you review and merge everything into `feature/agent-harness-redesign`. Starting UI and eval work in weeks 1–2 instead of week 3 gives the plan a buffer.

| Person | Area | Prompts | Weeks 1–2 | Weeks 3–4 |
| --- | --- | --- | --- | --- |
| You | Integration, deployed commit, review loop, library source, demo story | N1, W2-3, W2-4, W4-2 | Decisions, `clusters.yaml`, merges, revision round | Comparison runs, slides, dry run, freeze |
| Teammate 1 \[name\] | Finding the target and routing | W1-1 (backend), W2-1, W2-2 | `find_workloads`, resolver, router, side questions | Fixes from reliability runs |
| Teammate 2 \[name\] | Console UI | W1-1 (choice buttons), W3-1, W3-2 | Choice buttons, then an early start on harness views | Replay mode, polish |
| Teammate 3 \[name\] | Evals | W1-2, W3-3, W4-1 | Scenario recordings, parity set | Scorecard data, reliability runs |

**Working rules**

- One branch per person off `feature/agent-harness-redesign`; one prompt, one small pull request with tests; you merge.
- Before each merge, the full test suite and the replay suite pass on the merged result.
- Shared files (graph state, `models.yaml`, the report builder) get announced in the morning sync before anyone changes them.
- A 15-minute sync every morning; the status doc is updated with each merge.
- Each person uses their own Copilot allowance for their prompts; the model comparison runs only from the approved project budget.

**Kick-off**

- [ ] Share this doc and Untitled with the team — Nov 2, 2026
- [ ] One-hour walkthrough: architecture, test entry point, replay suite, branch rules — Nov 2, 2026
- [ ] Request the 50k credit approval — Nov 3, 2026

## Scope freeze

A change goes in before the demo only if a demo scenario fails without it. Everything below waits, and several items become part of the ask.

- Kibana and Datadog connections
- Artifactory or registry tools
- Responses API and any production model change
- Per-user access controls
- Question bank at scale and the coverage gate in CI
- New skills beyond the four scenarios, AKS-specific skills, the survey of all 27 clusters
- Downstream dependency checks
- Further tuning of guards, citations and report wording

## Copilot credit budget

The 50k is yours alone; each of the three teammates has 15k for their own prompts, Opus included. Your 50k, once approved, covers your own prompts, the model comparison, top-ups for teammates who run low, and a reserve. Observed so far: about 190 credits for a small Sonnet change and about 2,000 for one large Opus task.

| Use of your 50k | Credits |
| --- | --- |
| Your prompts (N1, W2-3, W2-4, W4-2), reviews and fixes | 15,000 |
| Model comparison: 20 questions × 3 runs | 8,000 |
| Replays and reliability runs | 7,000 |
| Top-ups for teammates who run low | 8,000 |
| Reserve | 12,000 |
| Total | 50,000 |

- Opus for the five hard prompts; Sonnet for everything else.
- One prompt per task, with the checks in the prompt, so there is less back-and-forth.
- Everyone checks usage on Friday; anyone past 75% of their allowance before week 4 gets a top-up from the reserve.
- If the 50k isn't approved: run the comparison as 10 questions × 1 run (about 2,000), use Opus only for W1-1 and W2-1, and cut in this order: scorecard page polish, library source, the "Dig deeper" button.

## Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Live data moves on: the October 21 restarts age out, pods are redeployed, previous logs are gone | Scenarios 2 and 3 run as labelled replays; on November 30, choose a service with current restarts for the live follow-up |
| Investigations take 5–7 minutes, too long to watch live | Start scenario 2 early in a second tab; replay at 4x speed; target under 4 minutes |
| Network or VPN drops (connection errors seen October 29) | Retries are in place; switch to the backup recording |
| Credits run out | Budget above; Sonnet by default; cut order above |
| A week slips | Go/no-go on November 13; cut in the order above rather than moving the date late |
| A late change breaks something | Freeze on November 25; image built from the tag; rollback command tested |
| Showing data from a PCI-scoped UAT cluster (`digital-obc-k8-pci-uat02`) | Check with security before the dry run, or pick non-PCI scenarios |
| Anchor gets something wrong live | Point at the status label and "To confirm": saying what it doesn't know is part of the story |
