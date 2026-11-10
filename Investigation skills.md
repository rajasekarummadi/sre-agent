# Investigation skills

Investigations pass 4 of 10 today, and the time goes to the model improvising: in one run, 8 of 13 turns made no tool call. Each playbook below is what an experienced SRE does: one batch of reads, branches on what they show, a check of what changed, and a rule for when to stop. Copilot turns them into skill files (prompt S1), and the known-answer set checks that answers are right, not just given.

## How every skill works

Every playbook has the same six parts, so an investigation follows a plan instead of wandering.

1. **Target:** the confirmed service, cluster and namespace from the thread; never resolve it again. With several catalog matches, choose by the channel word (banker, consumer…) and verify with a read.
2. **First batch:** the listed reads, all in one turn.
3. **Branch:** follow the branch that matches what the first batch showed, and skip the others.
4. **What changed** in the window before the problem started: the last deploy and its commit (from the pipeline ID in the Deployment name), config changes in GitLab, ServiceNow change requests, VirtualService weight changes, Panorama commits. Search by the request path, not just the service: the app, its F5 VIP and pool, firewall rules, DNS and the cluster, plus every network-team change in the window, because a network change is logged against the F5 or firewall, not the app. This is change correlation, built from tools Anchor already has.
5. **Stop rule:** stop when there is a cause, at least two pieces of evidence for it, and at least one alternative ruled out. When time runs short, give the best-supported cause and mark the rest "not verified".
6. **Answer:** the cause in one sentence, cited evidence, what changed, what was ruled out, what wasn't verified, and the next step with who to engage.

**Time budget:** first batch done by 60 s, branch reads by 180 s, answer by 300 s.

**Everywhere:** Deployment names end in the pipeline ID, so older releases scaled to zero are normal. Work on the Deployment that owns the running pods, or the one the VirtualService routes to. Never read Secret data or exec into pods.

## Crash loop and restarts

**Use for:** restarts, CrashLoopBackOff, OOMKilled, pods not ready (the crash-\* questions and restart follow-ups).

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

**Tell:** never conclude "scaled to zero" without checking it's the subset the VirtualService actually routes to. Old releases at zero are normal.

## Pipeline failure

**Use for:** a failed pipeline or job, a deploy that didn't happen, "why did my build fail" (the ci-\* questions).

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

**Fifth playbook, errors or slowness without restarts.** First batch, one turn: error count and top error signatures for the service (Kibana once connected, pod logs until then); CPU and memory against limits; the last deploy; the downstream hosts named in the errors. Then follow the matching row in the table below.

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

**What Anchor can't see yet:** broker health, consumer lag, queue depth, database locks and slow queries. Those need read-only tools or metrics after the demo; until then Anchor says plainly what it couldn't check.

**It gets better with use:** this table is a file engineers extend, and each postmortem adds a row. To start with the right rows, pull the last 90 days of P1–P3 incidents for these services from ServiceNow and make sure their most common causes are covered.

## Known-answer incidents

The live test can't tell a right answer from a wrong one, because UAT may have no real incident when it runs. These cases can: you write the real cause in one line, and Anchor passes only if it names that cause, cites evidence for it, and answers within 300 s. Each case replays recorded tool results twice, so it is cheap and live data changing doesn't matter. The CIO headline becomes "on N real past incidents, Anchor named the cause in M, in a median of X minutes".

| # | Incident or thread | Service and environment | Real cause, one line | Playbook |
| --- | --- | --- | --- | --- |
| 1 | Thread 45a7ca8e | usb-dss-accounts, uat5 banker |  | Crash loop |
| 2 | bbds-grphqldep (aedc48f8) | bbds-grphqldep |  | Crash loop |
| 3 | ci-deploy-failed-no-link | usb-dss-authorization pipeline | Confirm Anchor's answer: a dependency's POM couldn't be downloaded | Pipeline failure |
| 4 | Last night's production incident |  |  | Incident triage |
| 5 |  |  |  |  |
| 6 |  |  |  |  |
| 7 |  |  |  |  |
| 8 |  |  |  |  |

Pick incidents whose cause you are sure of, with at least one per playbook, and include a 503.

## Prompt for Copilot (S1)

Opus. Send in the main chat after the rerun 5 report. Re-export this tab to `designdoc2/` first.

```text
S1: investigation skills. Playbooks: designdoc2/Investigation skills.md.
Rules: .github/copilot-instructions.md.

Report first, no changes:
1. Today's skill files, their template, and how a skill is chosen for an
   investigation.
2. For each playbook, the tools it names that don't exist under that name:
   map each to the real tool, or say it's missing.
3. Which parts the harness can enforce in code (first batch in one turn,
   time budget per stage, stop rule) and which stay as skill text.

After my go-ahead:
- Write the five skills in our template, keeping each playbook's order:
  first batch, branches, what changed, stop rule, answer shape.
- Choose the skill from the mode and the symptom; Triage hands off to the
  matching skill.
- Known-answer set in evals/rca/: one case per incident I list, replaying
  recorded tool results, with my one-line cause. Pass = names the cause,
  cites evidence, under 300 s. Run each case twice; report per case.
- The error-signature table as a data file the skills read, so engineers
  can add rows; the dependency checks run when a signature matches.
- Golden tests for each playbook's branches, with recorded responses.
- One logs step in every skill: Kibana tools when ANCHOR_KIBANA is on, pod
  logs otherwise. Kibana is being built in parallel on feature/kibana and
  will bind to that step after this merges.
No new tools and no new flags. Full suites green before each commit.
```
