# Anchor: rules for Copilot

Anchor is a read-only SRE agent (anchor-main plus MCP servers). Goal: a demo to 12 directors, then the CIO demo on Dec 1, 2026. Plan: designdoc2/Plan.md. Investigations: designdoc2/Investigation skills.md. Kibana: designdoc2/Kibana plan.md.

## Scope
Build only what the current prompt asks. In scope until Dec 1:
- Fixes that raise the pass rate on the 64 frozen questions in evals/questions.yaml
- Investigation skills and the known-answer set (S1), and the ServiceNow lookup fix (N2)
- Stop and steer for investigations (S2a, then S2b)
- Kibana fixes (U4 is merged; ANCHOR_KIBANA is on by default and stays as the off switch)
- Smoke tests, and thumbs up or down feedback for the pilot
- The four demo scenarios

Out of scope until after Dec 1 unless the owner says otherwise: Datadog, pcap analysis, remediation or any write action, new MCP servers (anchor-f5 included, until F5 read access is approved), automatic mode routing, Responses API or model changes, per-user access controls, UI redesign, a CI coverage gate.

Design changes, new tools, new permissions or anything out of scope: report and stop for the owner's go-ahead.

## Safety
- Read-only. No exec into pods. Never read or store Secret data.
- No production namespaces in live runs. TLS verification on; credentials from config only.
- Never print, log or commit tokens or API keys (.anchor-local/.env, .anchor-local/api-token).

## Finding the target
- Catalog first: service -> environment -> cluster + namespace. Verify with a namespace-scoped read; that read is the evidence.
- If the catalog has no entry or the read says not found: search the other namespaces the catalog lists for that environment, namespace-scoped, and say the entry is missing or stale.
- Never depend on cluster-level access. AKS is namespace-level only; on-prem varies. A cluster-wide call is an optional last resort where a cached check allows it; a denied one is expected, not a permission gap.
- One environment normalizer everywhere: uat1 = uat01 = uat-001 = UAT-001. uat1 never matches uat10; prod never matches preprod.

## Answers
- Every claim cites a tool result. Never invent a namespace, host or cluster.
- Never say something is not found, not visible or unavailable unless a tool result in that turn said so.
- A tool that can't answer for this target (an error, "unknown service", "not mapped") means not checked: say so, never "no results".
- Ask the user about a target only after the lookups that could answer it were tried in that turn.
- Logs come from Kibana first; anchor-kube pod logs only as the fallback in the Kibana plan.

## Changes
- Start each prompt from a clean working tree; never mix another task's pending edits into a commit. One prompt's changes per commit.
- Fix the class of problem, not one question; say which questions the fix covers.
- Before speeding up a path, check that it is the right path.
- Each fix gets a test that fails without it. Full suite green before every commit.
- The scorer and evals/questions.yaml are frozen. Never relax a test or an expectation without the owner's approval; show the diff.
- Flags: only ANCHOR_UNIFIED_PATH and ANCHOR_KIBANA. No new flags.
- Exact commands, never placeholders.
- Live runs: read-only, one question at a time, $15 cap per full run.
- Report results against the go/no-go bar in Plan.md: the bar's pass rate and the strict rate.
