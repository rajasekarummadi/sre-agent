# Speaker notes: peer demo (Nov 24)

Read-aloud notes for the 30-minute session with peer managers, in presenting order: a short opening, the live demo, the slides that explain what they just saw, then control, next steps and questions. There's about 20 minutes of material, which leaves 10 for questions. Fill in or check anything in \[brackets\] before the call. Paste each section into its slide's notes. Answers to likely questions are on the Peer demo prep tab.

| Part | Slides | Time |
| --- | --- | --- |
| Opening | Title, the problem, what Anchor does, three pillars | 3 min |
| Live demo | Demo | 8 min |
| How it works | Five stages, inside the harness, inside the loop | 5 min |
| Building blocks | Harness engineering, memory, tools, built with | 3 min (skim if short) |
| Close | People stay in control, where we are and what's next | 3 min |

## 1. Title (20 s)

"Thanks for making the time. I'm going to show you Anchor, a read-only AI agent we built to investigate failures across our Kubernetes estate. I'll keep the slides short: a couple of minutes of context, then a live demo, then how it works, and the rest of the time is yours for questions. Anchor is built around three ideas: harness engineering, memory and tools. I'll come back to each of them."

## 2. The problem (45 s)

"Everyone here has lived this. An alert fires or an incident opens, and the first part of the response isn't fixing anything. It's gathering context. Which pods, which namespace, what do the logs say, did routing change, did a pipeline deploy something, is there a change request, is the firewall involved?

That evidence is spread across Kubernetes, Istio, Kibana, GitLab, ServiceNow and Panorama, and each needs its own access and know-how. Google's SRE teams found that about 70% of outages follow a change to a live system, yet finding that change is often the slowest part. Anchor does the gathering and shows its evidence, so your engineers can decide faster."

## 3. What Anchor does (45 s)

"You ask in plain language and pick one of three modes. Ask is for quick questions, like 'is this service healthy' or 'which DNS name do I use', answered in seconds. Investigate is a full root-cause analysis. Triage starts from a ServiceNow incident.

Anchor only reads: it can't restart, scale or change anything. Every claim in its answer links to the evidence behind it. What you get back is either a direct answer, or a report with a status, the cause, what was ruled out, a suggested fix for a person to run, and an incident note ready to paste."

## 4. Three pillars (45 s)

"Three things make this work. **Harness engineering**: the code around the model that decides what it may do, for how long, and what counts as proof. **Memory**: what it carries between steps, between runs, and from our teams' knowledge. **Tools**: read-only access to the systems engineers already use.

Keep those three in mind. I'll show you them in action first, then come back to how each one works."

## 5. Live demo (8 min)

Before you start: say which parts are recorded ("recorded on \[day\] from UAT"), and keep production cluster names off the screen.

1. **Ask, live (1 min).** Type a status question. "Watch how quickly this comes back, and look at the citations: every line links to the tool result behind it. And if it can't see something, it says 'not checked', never 'no problem'."
2. **Investigate, recorded (3 min).** Open the captured run and pick it in Follow run on the Architecture tab. "This is a real investigation from \[day\]. Watch the stages light up: it confirms the target from our catalog, fires its first reads together, ranks its hypotheses, tests them, and then a reviewer checks the draft before we see anything." Point at the hypotheses as they're ruled out, and at an evidence ID.
3. **Steer and stop, live (1 min).** Start a new investigation, send one steer message, then press Stop. "I can redirect it mid-run: 'focus on Kafka' joins its next step. And I can stop it at any time. It keeps what it found and tells me what's left, and the cost stops when it stops."
4. **The report (2 min).** Walk the status, cause, evidence, what was ruled out, the suggested fix and the incident note. Click one evidence ID. "Look at the status. 'Established' means the causal check passed and every citation validated. It would rather say 'Probable' or 'Unknown' than overclaim, and the fix is a suggestion: a person runs it."
5. **Scorecard (30 s).** "This is how we know it's getting better and not quietly getting worse: pass rate on a fixed question set, time and cost per run."

If a live step stalls (gateway throttling, or nothing failing in UAT today): "That's our dev gateway being careful with us. Here's the same thing from earlier," and switch to the backup tab.

## 6. One investigation, five stages (90 s)

"Here's what you just watched, end to end.

**Intake.** The request is authenticated, sensitive values are redacted, and the target is confirmed from our service catalog, so the run starts from facts, not guesses.

**Orchestrate.** The mode you picked sets the budget. The agent chooses a playbook, such as crash loop, pipeline failure or 503 routing, writes its plan, and plans its first reads.

**MCP tools.** It reads Kubernetes, Kibana, GitLab, ServiceNow and the catalog through read-only tools. Each result is stored as evidence with an ID you can click.

**Evaluate.** Before anything is shown, the harness checks the work: are the tasks finished, is every claim cited? Then a separate reviewer checks the draft against the evidence, and the agent gets one round to fix what it flagged.

**Publish.** You get a status, the cause, the evidence behind it, what was ruled out, a suggested fix that it never runs, and an incident note ready to paste."

## 7. Inside the harness: what each part enforces (2 min)

**Intake.** "Input is redacted and size-checked before any model call. The run starts with only what it needs: the mode, the environment, the confirmed target, and the incident if it's Triage."

**Mode.** "You choose the depth, not a router guessing. Ask is quick: about 12 tool calls and two minutes. Investigate is a full root-cause analysis with review, with a hard time limit. Triage is Investigate plus the incident's context."

**Agent.** "This is the model's part. It plans the next read and can use every read-only tool, and finding the service and environment are tools too. It searches before it asks, and when it must ask, it gives you buttons, not a free-text quiz."

**Tools.** "The read-only allowlist rejects any write or unknown tool. Each playbook has a call budget. Every result is redacted, size-bounded and gets an evidence ID."

**The loop.** "Agent and tools go back and forth until the stop rule is met or the budget runs out. It ends on time with its best-supported answer, not when the model feels done."

**End-of-run checks.** "Open tasks, uncited claims and sources are checked. If something's missing, the run goes back to the agent, at most three times, and then it finishes and lists the gaps honestly."

**Reviewer and revision.** "A separate reviewer reads the draft against the cited evidence, and it can only suggest tools that actually exist. The agent gets one bounded round, at most three reads, to fix what was flagged, and you can watch that happen in the live feed."

**Report.** "The status tells you how much to trust it. 'Established' only when the causal check passes and every citation validates. 'Probable' when a mechanism is backed by live evidence. Otherwise 'Unknown', which is an honest answer, not a failure. A bad citation lowers the status automatically."

## 8. Inside the loop: one investigation, step by step (2 min)

Use this as a backup slide, or when someone asks how it actually thinks.

"Here's what happens between 'start' and the report.

**1. Pick the playbook.** A classifier reads the question and picks a skill, such as crash loop, pipeline failure, 503 routing, or errors and dependencies. Each skill is a playbook written by engineers: what to read first, how to branch, and when to stop.

**2. Write the plan.** The model drafts a task list for this investigation from that playbook: confirm the target, establish scope and onset, check what changed, then the playbook's own checks. The plan is tracked by the harness, updated every turn, and the run can't finish while a task is still open.

**3. First batch, in one turn.** The harness, not the model, fires the opening reads together: scope (one pod, one service, or many), onset (when errors started), and what changed just before, such as the last deploy, config changes and routing weights. Changes come first because most outages follow one.

**4. Hypotheses.** From those results the agent ranks two to four candidate causes. They're kept as tracked state and shown live, so you can see what it's thinking.

**5. Test and branch.** Each turn, it picks the cheapest read that tells the hypotheses apart, and marks each one confirmed, ruled out or open. Error text is matched against a signature table engineers maintain; for example, 'Hikari pool exhausted' points to the database. The playbook says which branch to follow next.

**6. Guardrails every turn.** Only read-only tools, a call budget per playbook, and caps on repeating the same call. Every result becomes evidence with an ID. If a tool can't see something, that's recorded as 'not checked', never as 'no problem'.

**7. You can step in.** Every step is checkpointed. A message you send mid-run is picked up before the next turn. Stop ends it immediately, keeps the evidence, and lists the open tasks as 'what's left'.

**8. Time checkpoints.** First batch by about a minute, hypotheses tested by about three, and a hard limit at seven. When time runs short, it reports its best-supported cause and marks the rest 'not verified'.

**9. Stop rule.** It stops when one cause has evidence and an alternative has been ruled out, or when the budget is spent. Never just because the model feels done.

**10. A false premise is an answer.** If the service is healthy or the errors aren't there, it says so with evidence, rather than inventing a cause to fit the question.

Then the end-of-run checks, the reviewer, the revision and the report take over: the part on the previous slide."

Don't claim yet: that the plan is strictly enforced (the model can still mark some tasks 'not needed'; a fix is built, not deployed), source-code reads behind an error, or ServiceNow change and past-incident searches. Those are next.

## 9. Harness engineering (60 s)

"So that's the harness. Everyone has access to the same models. What makes an agent dependable is the code around the model. The model decides what to look at next; the harness decides what it's allowed to do, how long it can take, and what counts as proof.

The loop is fixed in code and the mode sets its budget. Only read-only tools are on the allowlist, so a write is impossible, not just discouraged. Every tool result gets an evidence ID, and a claim without one doesn't count. Every answer passes a completion check, an independent reviewer and one round of revision. And more than 2,250 automated tests keep all of that from quietly breaking."

## 10. Memory (60 s)

"Memory works at four levels. **Thread memory**: once a service is confirmed, follow-ups in the same thread keep it, so you never re-explain. **Run memory**: every step is checkpointed in Postgres, so a stopped or restarted run keeps its evidence. **Evidence memory**: every read is stored with an ID and can be opened from the report, which is also our audit trail. **Team memory**: the service catalog, about 30 playbooks written by engineers, and an error-signature table anyone can extend. Each postmortem can add a row.

Next: past ServiceNow incidents, so a match with a known issue gets tested first."

## 11. Tools (60 s)

"Anchor reaches our systems through MCP servers. MCP is an open standard for connecting AI agents to tools. We have \[six\] servers, all read-only: Kubernetes and Istio (pods, events, workload specs, routing, DNS, TLS, network policies), Kibana logs (error trends and top error signatures), GitLab pipelines and job logs, ServiceNow incidents, the service catalog, and Panorama firewall rules.

It works with namespace-level access, which is what we have on AKS and much of on-prem, and never depends on cluster-wide rights. Because MCP is a standard, the same tools can be used from Copilot or Claude Code too. Next, once access is approved: F5, Datadog and Artifactory."

## 12. Built with (45 s)

"It's built from standard, open pieces: Python with LangGraph for the agent loop and its checkpoints, GPT-5.1 on our Azure OpenAI through the APIM gateway, MCP for read-only tools, a FastAPI service streaming to a React console, and Postgres for memory. Playbooks are Markdown files engineers can edit, and it ships through Docker and GitLab CI like any other service. We built it with GitHub Copilot.

We chose pieces that are open and already approved, so nothing is locked in and security has nothing exotic to review. The value isn't in any one of these. It's in the harness that ties them together, and in our playbooks."

## 13. People stay in control (60 s)

"Engineers stay in charge at every point. You can **stop** it at any time: it gives you a partial report with what it checked, its current hypotheses and what's left, and the cost stops too. You can **steer** it mid-run: a message like 'focus on Kafka' joins its next step. You can **continue** after the report with more context or 'that's wrong because…' \[live / rolling out this week\].

And the guardrails don't depend on the model behaving: read-only tools, no access to secrets, no production namespaces in live runs, and fixes are suggested, never executed."

## 14. Where we are and what's next (90 s)

"Where we are: \[latest result on our 64-question evaluation, against a 55/64 bar\]. Investigations take a median of about \[four\] minutes, with a hard limit, and each run shows its cost: recent ones were around \[$0.10 to $0.40\].

What's next: wider demos to leadership, and a pilot with on-call engineers from different teams. That's where I'd love your help. Send me your five most common recurring incidents, so we can make sure there's a playbook for them, and lend one engineer to the pilot to ask real questions and tell us when it's wrong.

Our asks to unlock more: read access to F5, Datadog, Artifactory, and production logs in Kibana, with security sign-off.

That's it from me. What questions do you have?"
