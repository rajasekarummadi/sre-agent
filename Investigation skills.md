# Investigation skills

Every investigation follows one method: confirm the target, establish scope, onset and what changed, check known issues, then test ranked hypotheses with the cheapest evidence first. The playbooks cover the failures SREs actually meet in this estate: on-prem Rancher and AKS clusters, Istio, F5, Panorama, Vault-synced secrets, GitLab CI, Spring Boot, SQL Server, Kafka, IBM MQ and Redis. Copilot turns them into skills (S1); stopping and steering an investigation is specified at the end (S2).

## The method

Every playbook runs the same steps, so an investigation follows a plan instead of wandering. Steps 2–4 go in the first batch, in one turn.

1. **Target:** the confirmed service, cluster and namespace from the thread; never resolve it again. With several catalog matches, choose by the channel word (banker, consumer…) and verify with a read.
2. **Scope and onset:** how wide is it, and when did it start? One pod, all pods of the service, one site or cluster, or many services (the same error signature elsewhere in Kibana)? Onset comes from Kibana's error histogram, or from restart and event times. Scope sets direction: one pod points to that pod or its node; one service to its code, config or a dependency; many services to something shared, such as a dependency, the gateway, DNS, the F5, the firewall or the cluster.
3. **What changed** in the window before onset: the last deploy and its commit (from the pipeline ID in the Deployment name), config changes in GitLab, ServiceNow change requests, VirtualService weight changes, Panorama commits. Search by the request path, not just the service: the app, its F5 VIP and pool, firewall rules, DNS and the cluster, plus every network-team change in the window. Changes come first because roughly 70% of outages follow a change to a live system ([Tenets of SRE](https://oreilly.com/ideas/tenets-of-sre)).
4. **Known issues:** past ServiceNow incidents from the last 90 days for the same service or error signature. If one matches, test its recorded cause first and cite it.
5. **Hypotheses:** two to four candidate causes from steps 2–4, ranked by likelihood. Test the cheapest evidence that tells them apart, and mark each one confirmed, ruled out or open. The list is shown live, so the engineer can steer.
6. **Branch:** follow the playbook branch that matches the evidence, and skip the others.
7. **Stop rule and confidence:** Verified means a cause, two pieces of evidence and one alternative ruled out. Likely means a cause with one piece of evidence and nothing against it. Possible means consistent but untested. When time runs short, give the best-supported cause with its level and mark the rest "not verified".
8. **Mitigation:** the fastest safe way to restore service, as a suggestion for a person to run, with the exact step: roll back to the previous pipeline, shift VirtualService weight back, scale out, or fail over to the other site. Anchor never runs it.
9. **Answer:** the cause in one sentence with its confidence level, cited evidence, what changed, what was ruled out, what wasn't verified, the mitigation, who to engage (the ServiceNow assignment group), and a short incident note ready to paste.

**Time budget:** checkpoints at 60 s (first batch) and 180 s (hypotheses tested), within today's 420 s limit; target median under 300 s.

**Everywhere:**

- A false premise is an answer. If the logs show no errors or the service is healthy, say so with the evidence; never invent a cause to fit the question.
- Deployment names end in the pipeline ID, so older releases scaled to zero are normal. Work on the Deployment that owns the running pods, or the one the VirtualService routes to.
- Never read Secret data or exec into pods.

## Coverage map

Each failure engineers actually report maps to one playbook; the last column says what Anchor still can't see.

| Scenario | Playbook | Gap today |
| --- | --- | --- |
| Pods crash-looping, OOMKilled, probe failures | Crash loop and restarts | None |
| 503s, "no healthy upstream", route not found, auth rejected at the gateway | 503 and routing | None |
| Users failing while the cluster looks healthy | 503 and routing (upstream row) | F5 config: no read access |
| Errors right after a deploy, rollout stuck, canary gone wrong | Bad rollouts and environment differences | None |
| Works in one environment, not another | Bad rollouts and environment differences | None |
| Expired or untrusted certificate, mTLS errors | Certificates and TLS | F5 certificates |
| Pipeline or deploy job failed | Pipeline failure | None |
| Pending pods, quota, HPA at maximum, throttling, evictions | Capacity and scheduling | Node details on prod-hosting and AKS clusters |
| One pod or one site failing, intermittent errors, same time every day | Partial and intermittent failures | None |
| Slow responses or timeouts without restarts | Errors, slowness and dependencies | Metrics history (Datadog) |
| Database, Redis, Kafka or MQ failures | Errors, slowness and dependencies | Broker health, consumer lag, queue depth, database locks |
| Credentials rotated, Vault sync failed | Errors, slowness and dependencies | None |
| Firewall or network change blocking traffic | 503 and routing; checks for any dependency | None |
| ServiceNow incident, "broken since last night" | Incident triage | ServiceNow lookups fail for real services until N2; production data needs approval |

## Crash loop and restarts

**Use for:** restarts, CrashLoopBackOff, OOMKilled, pods not ready (the crash-* questions and restart follow-ups).

**First batch, one turn:** pods with restarts and readiness; each pod's last termination (reason, exit code, time) from `kubernetes_pod_crash_diagnostics`; namespace events from the last 2 hours; the Deployment's resources, probes and image.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| OOMKilled, exit 137 | Memory limit against usage; heap flags (-Xmx) in the container args | Limit too low for the heap, or a leak |
| Exit 137, not OOMKilled | Events: liveness probe failures, evictions, node pressure | Liveness probe killing a slow app, or eviction |
| Exit 143 | Rollout history, scaling events | A normal rollout or scale-down, not a crash |
| Exit 1 or another app code | Previous container's logs (Kibana first once connected): the first exception and its cause | Config, dependency or code error |
| CreateContainerConfigError | ConfigMap and Secret references in the spec, names only | A referenced ConfigMap or Secret is missing |
| ImagePullBackOff | Image tag and the pipeline that built it | Tag never pushed, or registry access |
| Not ready, no restarts | Readiness probe config; reachability of what it checks | A dependency the probe checks is down |

**Tells:** restarts at the same moment on different nodes point to the app or its config, not a node. Restarts that began right after a deploy point to that deploy.

## 503 and routing

**Use for:** 503, 502, 504, "no healthy upstream", timeouts through the gateway, a host that doesn't answer (routing-503, triage-no-number, routing and exposure questions).

**First batch, one turn:** Istio host search for the hostname (Gateway, then VirtualService, then destination Service and subset); ready endpoints behind that Service; the DestinationRule (subsets, TLS mode, outlier detection); readiness of the pods behind the routed subset.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| Zero ready endpoints, pods failing | Run the crash loop playbook on those pods | The app is down |
| Zero endpoints, routed subset scaled to zero | VirtualService weights against the Deployment versions | Traffic routed to a release with no pods |
| Endpoints ready, still 503 | Subset labels against pod labels; Service port names; DestinationRule TLS mode against mTLS policy | Label, port or mTLS mismatch |
| Response flags in access logs (once Kibana is connected) | UH no healthy upstream, UF connection failure, URX retries exhausted, NR no route, UO circuit breaker | The flag names the failure |
| Fails only from outside | TLS probe and DNS resolution; Panorama rule for the path | Certificate, DNS or firewall |
| Pods, endpoints and routes healthy, users still failing | Traffic at the ingress gateway (Kibana access logs): a sudden drop, or health checks from the F5's addresses now getting 404 or 503; DNS for the hostname; an HTTP probe of the public hostname, labelled with where it ran from; F5, firewall and DNS changes in the window | Upstream of the cluster: the F5 health monitor (ECV), VIP or pool, a firewall rule, or DNS |
| Pod shows 1/2 ready, or no sidecar | Namespace injection label; sidecar status | Sidecar missing or not started, so mTLS fails |
| 404 with flag NR from the gateway | VirtualService hosts and gateway binding | No route for that host or path |
| 401 or 403 at the gateway | EnvoyFilter Lua auth, AuthorizationPolicy, RequestAuthentication | An auth filter rejecting the request (token, JWKS or policy) |
| 431 or 413 | Header and body size limits | Oversized headers (cookies, tokens) or bodies |

**Tell:** never conclude "scaled to zero" without checking it's the subset the VirtualService actually routes to. Old releases at zero are normal.

## Pipeline failure

**Use for:** a failed pipeline or job, a deploy that didn't happen, "why did my build fail" (the ci-* questions).

**First batch, one turn:** the GitLab project (catalog repo, then the image label, then `search_projects`); recent pipelines for the branch; the failed jobs and the last 200 lines of each job's log; the job's definition in `.gitlab-ci.yml`.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| "Could not resolve", artifact descriptor, 401/403/404 from Artifactory | Which artifact and version; whether it was ever published; the last green pipeline's version | A dependency version not published, or registry access |
| Test failures | First failing test; whether it also fails on the default branch | A new break, or a flaky test |
| Image build or push error | Base image tag; registry response | Base image moved, or push denied |
| Deploy job error | The Helm or kubectl error; namespace quota or policy; then the crash loop playbook if pods fail after the deploy | Bad manifest, quota, or the app failing on start |
| Job timeout, no runner, job out of memory | Runner tags, retries, job resources | Runner capacity |

**What changed:** compare the last green pipeline with the first red one: commits, `.gitlab-ci.yml` changes, dependency and parent POM version bumps.

## Incident triage

**Use for:** Triage mode, a ServiceNow incident number, or "X has been broken since last night". This is where the change story lands for the CIO.

1. **Incident:** read the record: description, affected service, opened time, priority, assignment group. With no number, take the service and time from the message; with no time, ask one button question: last 30 minutes, last 2 hours, today, or since yesterday evening.
2. **Onset:** find when errors actually started: Kibana error onset once connected; until then, restart and event timestamps.
3. **Symptom:** classify it and run the matching playbook: crash loop, 503 and routing, or pipeline failure.
4. **Change timeline:** every change in the 24 hours before onset (deploys and their commits, config changes, VirtualService weights, ServiceNow change requests, Panorama commits), ordered by how close each lands to the onset.
5. **Answer:** the likely cause and confidence, the suspected change with its time and author, what was ruled out, who to engage (the incident's assignment group), and the next step.

**For the demo:** last night's production incident is the strongest possible example, if security approves its data or it can be reproduced in UAT. Anchor names the change, shows that errors began right after it, and cites the diff.

## Errors, slowness and dependencies

Most application failures surface as a Java exception in the logs, and the root exception (the last "Caused by:") names the dependency. Anchor can't log in to databases, Redis, Kafka or MQ, so it works from logs, config, the network path and recent changes.

**Playbook for errors or slowness without restarts.** First batch, one turn: error count and top error signatures for the service (Kibana once connected, pod logs until then); CPU and memory against limits; the last deploy; the downstream hosts named in the errors. Then follow the matching row in the table below.

**Checks for any dependency**

1. **Where it points:** host, port and settings from `application.yml` or the Helm values in GitLab, and the pod's environment variable names.
2. **Blast radius:** the same error in other services at the same time means the dependency itself is down; only this service means its config, credentials or path.
3. **Network path:** DNS resolution of the host; Istio ServiceEntry for external hosts; NetworkPolicy in the namespace; the Panorama rule from the cluster to host and port.
4. **TLS:** TLS probe of host and port (dates, chain); truststore settings in the spec, names only.
5. **Credentials:** the Vault sync status and time for the secret, never the Secret itself; any recent rotation.
6. **Changes:** deploys of this service; ServiceNow changes on the dependency (database maintenance, Kafka or MQ work); Panorama commits.

| Exception or log text | Points to | Check first |
| --- | --- | --- |
| `HikariPool … Connection is not available, request timed out` | Database pool exhausted | Pool size against replicas; long transactions in the logs; database-side change |
| `The TCP/IP connection to the host … has failed`, `Connection refused` | Database unreachable | Network path; database maintenance change |
| `Login failed for user`, `password authentication failed` | Database credentials | Vault sync status and rotation time; recent deploy |
| `PKIX path building failed`, `SSLHandshakeException` | TLS trust | TLS probe of the target; truststore and CA settings; a certificate renewed with a new chain |
| `RedisConnectionFailureException`, `RedisCommandTimeoutException` | Redis | Host, port and TLS settings; a Redis failover or change |
| `Topic … not present in metadata`, `SaslAuthenticationException`, `CommitFailedException` | Kafka | Bootstrap servers; credential sync; consumer rebalances (`max.poll.interval.ms`); broker change |
| MQ reason codes 2035 (not authorized), 2059 (queue manager unavailable), 2009 (connection broken), 2538 (host not available) | IBM MQ | Channel and queue manager settings; network path; MQ change requests; TLS cipher and certificate |
| `SocketTimeoutException`, `ReadTimeoutException`, `Connection reset`, `CallNotPermittedException` (circuit open) | A downstream REST call | Which host; if it's in the cluster, the 503 playbook on that service; timeout and retry settings |
| `upstream connect error or disconnect/reset before headers` | Mesh path to a downstream | The 503 playbook on the downstream service |
| `APPLICATION FAILED TO START`, `Failed to bind properties`, `Could not resolve placeholder` | Spring Boot startup config | Which property; ConfigMap or values change; the active Spring profile |
| `OutOfMemoryError: Java heap space` or `Metaspace` | JVM memory | Heap flags against the container limit; a traffic or data change |
| `UnknownHostException` | DNS | Resolver config; the name's namespace; ServiceEntry |
| `RejectedExecutionException`, requests queueing | Thread pool exhausted | A slow downstream holding threads; pool size |
| `GC overhead limit exceeded`, long GC pauses | JVM memory pressure | Heap against the container limit; a traffic change |
| 401, `invalid_client` or an expired token from a downstream API | OAuth client credentials | Vault sync status and rotation time for the client secret |

**What Anchor can't see yet:** broker health, consumer lag, queue depth, database locks and slow queries. Those need read-only tools or metrics after the demo; until then Anchor says plainly what it couldn't check.

**It gets better with use:** this table is a file engineers extend, and each postmortem adds a row. To start with the right rows, pull the last 90 days of P1–P3 incidents for these services from ServiceNow and make sure their most common causes are covered.

## Bad rollouts and environment differences

**Use for:** errors right after a deploy, a rollout that doesn't finish, a canary or weight shift gone wrong, and "it works in uat4 but not uat5".

**First batch, one turn:** rollout status of the new and old Deployments (ready replicas, progress deadline); the last two pipelines and their commits; VirtualService weights. For environment questions, the same service in both environments: image tag, chart and values version, environment variable names, resources, Istio config.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| New pods not ready, old ones fine | New pods' logs and probes; config diff between the two versions | The new release; suggest shifting weight back or rolling back |
| Rollout stuck past its progress deadline | Events: scheduling, quota, image pull | Capacity or image problem (see Capacity and scheduling) |
| Errors only from one version or subset | Access logs split by subset | That version; suggest moving weight back to the good one |
| Deploy fine, errors start minutes later | Error onset against traffic; pool and cache settings; scheduled jobs | Warm-up, connection pools or load, not the code itself |
| Works in one environment, not the other | Diff of image, values, variable names, ConfigMap and Secret names, Istio config, dependency hosts, firewall path | The first difference on the failing path |

**Tell:** in an environment comparison, report only differences that touch the failing request path. A long list of unrelated differences hides the one that matters.

## Certificates and TLS

**Use for:** expiring or expired certificates, handshake and `PKIX` errors, mTLS failures between services, browser certificate warnings.

**First batch, one turn:** TLS probe of the hostname (expiry, chain, names); cert-manager Certificate status for the Gateway's credentialName on non-prod clusters; DestinationRule TLS mode and PeerAuthentication for the namespace; certificate renewals and changes in the window.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| Expired or close to expiry | Certificate status and renewal events | Renewal failed (issuer or validation) |
| Renewed recently; Java clients fail with `PKIX` | The new chain against the clients' truststore settings | A new intermediate CA the clients don't trust |
| Name mismatch | Certificate names against the hostname | Wrong certificate on the Gateway |
| mTLS errors between services | PeerAuthentication against DestinationRule TLS mode; a sidecar on both pods | mTLS mode mismatch, or a pod without a sidecar |
| Fine inside the cluster, fails through the F5 | F5 SSL profile or certificate changes in ServiceNow | F5 certificate or profile; hand to the network team |

## Capacity and scheduling

**Use for:** pending pods, slow scale-up, throttling, quota errors, evictions.

**First batch, one turn:** pod phase and scheduling events (FailedScheduling reasons); ResourceQuota used against hard limits in the namespace; HPA current, desired and maximum replicas; CPU and memory against requests and limits.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| Pending, insufficient CPU or memory | Requests against what nodes offer (say so when nodes can't be read) | Cluster full, or requests too large |
| Pending, quota exceeded | Quota usage by workload | Namespace quota reached |
| HPA at maximum replicas | Traffic trend; the HPA's metric | Load beyond the configured maximum |
| Slow, CPU near its limit | Usage against limits over time | CPU throttling |
| Pods evicted | Eviction events and reasons | Node memory or disk pressure |

## Partial and intermittent failures

**Use for:** errors from some pods or one site only, failures that come and go, problems at the same time every day.

**First batch, one turn:** errors split by pod, version and site (Kibana); the age, node and restarts of each pod; recent changes per site.

| First batch shows | Next reads | Usual cause |
| --- | --- | --- |
| Errors from one pod only | That pod's node, age, version and restarts; outlier ejection | A bad pod or node; suggest replacing the pod |
| One site or cluster only | Versions, config and dependency path compared between sites | A site-specific change or dependency |
| Comes and goes, no pattern | Errors against pods, versions and time; retry and pool settings | A flaky dependency, pool exhaustion or DNS caching |
| Worse every few hours, restarts fix it | Restart intervals; memory trend | A memory or connection leak |
| Same time every day | Scheduled jobs, batch windows, secret rotation times | A scheduled job or rotation |

## Known-answer incidents

The live test can't tell a right answer from a wrong one, because UAT may have no real incident when it runs. These cases can: you write the real cause in one line, and Anchor passes only if it names that cause, cites evidence for it, and finishes within the 420 s limit. Each case replays recorded tool results twice, so it is cheap and live data changing doesn't matter. The CIO headline becomes "on N real past incidents, Anchor named the cause in M, in a median of X minutes".

| # | Incident or thread | Service and environment | Real cause, one line | Playbook |
| --- | --- | --- | --- | --- |
| 1 | usb-dss-accounts-2a3d5954 (45a7ca8e made no tool reads) | usb-dss-accounts, uat5 banker |  | Crash loop |
| 2 | bbds-grphqldep (aedc48f8) | bbds-grphqldep | Hibernate can't load org.hibernate.dialect.SQLServer2008Dialect, so pods crash on start (recorded RCA; confirm) | Crash loop |
| 3 | ci-deploy-failed-no-link | usb-dss-authorization pipeline | Shield 403: the deploy user isn't in an allowed deploy group (from the job log) | Pipeline failure |
| 4 | Last night's production incident |  |  | Incident triage |
| 5 |  |  |  |  |
| 6 |  |  |  |  |
| 7 |  |  |  |  |
| 8 |  |  |  |  |

Pick incidents whose cause you are sure of, with at least one per playbook, and include a 503.

## Prompt for Copilot (S1)

Opus, in the main chat now that Kibana has merged; S2 follows it. Re-export this tab to `designdoc2/` first.

```text
S1: investigation skills, second pass. Method and playbooks:
designdoc2/Investigation skills.md. Rules: .github/copilot-instructions.md.

Report first, no changes:
1. Every skill file today, including those converted in the Kibana work,
   and which playbook in the doc each one covers.
2. Playbooks with no skill yet.
3. Tools a playbook names that don't exist: map each to the real tool, or
   mark it missing.
4. Which parts of the method the harness can enforce in code (scope, onset
   and changes in the first batch; hypotheses kept as state and shown live;
   time budget per stage; stop rule and confidence level) and which stay as
   skill text.

After my go-ahead:
- Apply the method to every skill: target, scope and onset, what changed,
  known issues, ranked hypotheses, branches, stop rule with confidence
  level, mitigation suggestion (never executed), answer with incident note.
- Add skills for playbooks with none: bad rollouts and environment
  differences, certificates and TLS, capacity and scheduling, partial and
  intermittent failures. Merge with existing skills (cert, egress,
  istio-503, springboot, database, kafka...) instead of duplicating them.
- Known issues: search ServiceNow incidents from the last 90 days for the
  same service or error signature; test a match's recorded cause first. If
  anchor-now can't search incidents that way, tell me.
- A false premise is an answer: no errors or a healthy service is reported
  with evidence, never explained away with an invented cause.
- The error-signature table as a data file engineers extend.
- Known-answer set in evals/rca/: one case per incident I list, replaying
  recorded tool results, with my one-line cause. Pass = names the cause,
  cites evidence, within 420 s. Run each case twice; report per case.
- Golden tests for each playbook branch, with recorded responses.
No new flags. Full suites green before each commit.
```

## Prompt for Copilot (N2)

Sonnet, in its own chat in the anchor-servicenow repo; it can run alongside S1. It makes the known-issues and what-changed steps work for real services.

```text
N2: ServiceNow lookups for real services. Repo: the anchor-servicenow
server (anchor-now). Rules: .github/copilot-instructions.md in
anchor-main-v2. From the S1 report: now:related_incidents and
now:list_changes fail for every real service ("Unknown service
'usb-dss-accounts'. Known services: payments-api") because the service map
has one placeholder entry, and there's no search by error text.

Report first, no changes:
1. How a service name becomes a ServiceNow query today (CI, business
   service, assignment group or text), and where the map is loaded from.
2. Which catalog field can fill the map, how many catalog services would
   map, and which wouldn't.

After my go-ahead:
1. Fill the service map from the catalog at startup (read-only, cached);
   remove the placeholder.
2. related_incidents: optional text search on short_description and
   description (last 90 days, at most 20 results, fields trimmed).
3. list_changes: the same mapping, plus optional text search (hostname,
   F5 pool or VIP name) and an assignment-group filter, so network-team
   changes on the request path show up in the window.
4. An unmapped service returns "not mapped", which Anchor reports as not
   checked.
5. Tests with recorded ServiceNow responses. Read-only: no work notes, no
   writes. Tell me what to deploy.
```

## Stop and steer

Engineers need to stop an investigation and to steer it, both while it runs and after the RCA; today only steering during a run works. On-call engineers often know something the tools can't show, and a CIO will ask whether a person can redirect the agent.

- **Stop:** a Stop button while it runs. Stopping cancels the model call and any pending tool calls, keeps what was gathered, and returns a short partial report: what was checked, the current hypotheses and what's left. The thread stays open with Continue, and cost stops when it stops.
- **Steer during a run:** a message sent while it runs ("focus on Kafka", "the deploy was a no-op") joins the next turn as context, without restarting.
- **Continue after the RCA:** Add context, Dig deeper (on any hypothesis or ruled-out item), That's wrong because…, or free text. Anchor continues the same investigation from its checkpoint: it keeps the evidence, treats the input as a new lead, re-ranks the hypotheses, works within 180 s, and shows what changed from the first answer.
- **Trust:** what the engineer says is labelled "from you" in the evidence, never as verified. If it contradicts tool evidence, Anchor says so.
- **One trail:** stops, steers and continuations stay on the same thread and in the audit log.

**What exists today** (Copilot's discovery, Nov 17): Anchor runs its own runner, not LangGraph's server. A FastAPI route starts one asyncio task per investigation, which streams the graph with the AsyncPostgresSaver checkpointer (thread_id is the investigation ID) and sends events to the UI over SSE. Steering during a run already works: the steer box and chat guidance queue the text, and the run picks it up between model turns. Three things are missing. There is no stop route, and a cancelled task stays "running" until the sweeper marks it failed. Continue after the RCA starts a fresh investigation without the old evidence. Questions sent during a run ("why…?") skip steering and can start a second run. S2a and S2b build on these pieces: no custom queue, cancel flags or second state store.

## Prompts for Copilot (S2a and S2b)

S2a goes to the main chat (Opus), with four quick items from the S1 runs first. S2b follows once S2a is merged, likely after Dec 1 unless the director demo needs it. The catalog latency prompt (C1) runs in a separate Sonnet chat.

```text
Pause the known-answer and fair-S1-test work; there are no proper incidents
to test against. Quick items first, each with a test, one commit each:
1. Smoke-script fix as you proposed (approved): detect an investigation by
   intent == investigate and mode != ask; send explicit Investigate mode
   for the pipeline and typed steps.
2. RCA writer: when the summary fails validation for length, shorten and
   retry once; never drop the cause claim or its evidence IDs.
3. ask_user: cap at the 6 top-ranked options instead of being rejected.
4. Classifier check, no tools: run only the skill classifier on the 64
   frozen questions and the smoke questions, on pre-s1-2026-11-17 and on
   cbbc009; report skills that changed. If pipeline or job questions now go
   to deployment-rollout-failure, narrow its description to Kubernetes
   rollouts and add a golden row.

Then S2a: Stop button for investigations. Spec: designdoc2/Investigation
skills.md, section "Stop and steer". Rules: .github/copilot-instructions.md.
Build on your Nov 17 discovery report; re-check its line numbers after S1.
Plan first: the files you'll change and how, in a short list. Build after
my go-ahead.
1. Route: POST /v1/investigations/{id}/stop cancels the run's task.
   Stopping a run that isn't running returns 409, like /steer.
2. On cancellation: status "stopped", never "failed", and the orphan
   sweeper leaves it alone. Partial report from the checkpoint (aget_state):
   what was checked, current hypotheses, what's left. No model call: a
   template over the state. Emit a "stopped" event for the SSE stream and UI.
3. Tell me whether langchain-mcp-adapters sends an MCP cancel notification;
   if not, that's acceptable (read-only tools).
4. UI: a Stop button beside the steer box while a run is running; after a
   stop, show the partial report and a Continue button (until S2b, Continue
   starts a new investigation for the same target).
5. Log a startup warning when ANCHOR_CHECKPOINTER_DSN is unset and the app
   falls back to MemorySaver.
6. Tests: stop during a model call; stop during parallel tool calls; status
   stays "stopped" after a sweeper pass; no model call after the stop; stop
   on a finished run returns 409.
Golden set green, no new flags, full suites green before each commit.
```

Then S2b, after S2a is merged (likely after Dec 1):

```text
S2b: steering fixes and continue after the RCA. Spec: designdoc2/
Investigation skills.md, section "Stop and steer". Rules:
.github/copilot-instructions.md. Start after S2a is merged.

Plan first: the files you'll change and how, in a short list. Build after
my go-ahead.

1. While a run is active on a chat thread, no message starts a second
   investigation. Questions ("why", "what", "?", conversations.py:~170)
   and messages under the 0.9 confidence bar become guidance for the
   running investigation, which answers them in its next update. No extra
   model call for them: the dev gateway is already throttling.
2. When the run picks up guidance (native.py:815-816, investigation.py:2762),
   emit "steering_applied" and show it in the UI at that point.
3. User statements (guidance and Continue input) go into the evidence
   labelled "from you", never verified. If one contradicts tool evidence,
   say so.
4. Continue after the RCA or after a stop: buttons Add context, Dig deeper
   (per hypothesis or ruled-out item), That's wrong because..., and free
   text. Start a new run linked to the previous one (parent investigation
   ID, same chat thread, appended to investigation_ids), seeded from the
   previous run's checkpoint via aget_state: evidence, hypotheses,
   ruled-out items and the RCA. Don't re-run the graph on the old thread.
   Treat the input as a new lead, re-rank hypotheses, budget 180 s, and
   show what changed from the first answer. This replaces the
   last_lookup-only seeding (conversations.py:~444) for follow-ups on a
   finished or stopped investigation.
5. UI: the continuation appears in the same investigation view as a new
   section, not as a fresh investigation.
6. Tests: a question mid-run doesn't start a run; steering applied and
   shown; continue after the RCA keeps the evidence; continue with a
   contradicting statement; continue after a stop; worker restart between
   the RCA and continue (Postgres checkpointer).
Golden set green, no new flags, full suites green before each commit.
```

## Prompt for Copilot (C1: catalog latency)

Sonnet, in a separate chat. The report is read-only, so it can run alongside S2a; if the fix lands in anchor-main-v2, build it after S2a commits.

```text
Catalog lookups are slow. Report first, no changes:
1. Time each step of a target lookup on the deployed build for 5 recent
   threads: the catalog call, environment normalizing, the namespace-scoped
   verify read, any fallback search, and model turns in between. Where does
   the time go, and what changed since rerun 3, when lookups took about
   half a second?
2. What is called repeatedly within one run or across runs that could be
   cached?
After my go-ahead, if a cache is the fix: cache catalog responses only
(short TTL, keyed on the normalized service and environment), and drop an
entry when the verify read says not found. Never cache the verify read: it
is the evidence. Test, and report lookup time before and after.
```
