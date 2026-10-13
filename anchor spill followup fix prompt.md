# Prompt: Fix Anchor not reading its own spilled tool output

You are working in the **Anchor** codebase (`anchor-main`, LangGraph, GPT-5.1, MCP servers). Troubleshoot and fix the issue below. Read the relevant code first, confirm each cause before changing anything, and keep changes minimal. Follow the "Do not break existing behavior" rules from `anchor_upgrade_prompt.md` section 0 if that file is in the repo (feature flag, keep API/UI contracts, run evals before and after).

---

## 1. What happened

Investigation `7e60d31f-9afc-433f-b22e-be8ce0c2208a` (deployment `usbinsights-cbbdmacctattr`, Spring profile `uat-pci`, Java 21 with the Datadog agent):

- Anchor fetched the previous container logs. The output was large, so it was spilled to `/tmp/anchor-spill-nqcry8ud/tool-output-<id>.txt`.
- The preview shown to the model contained only the **start** of the log: JVM flags, Datadog tracer startup and tracer config JSON. No application error.
- The run ended with this under **Follow-up checks**:
  > Not attempted: … The exact application error causing the HTTP 500 startup probe failures and exit code 1 is unknown; please run `anchor-main:read_spilled_output(path='…', grep='ERROR|Exception')` to inspect the full previous container logs…
- Anchor **asked the user to run its own tool** instead of calling it. The root-cause evidence was in the spilled file and was never read.
- The log text is escaped several times over (`\\\\n`, `\\\"`), which suggests tool output is JSON-encoded on top of already-encoded JSON.
- An earlier view of what looks like the same investigation concluded "memory limit exceedance or memory leak leading to OOMKilled" at 49% confidence, using 7 model calls and ~90k tokens in ~5 minutes. This view cites **exit code 1** with startup probe HTTP 500s. An OOMKill normally shows exit code **137** with reason `OOMKilled`, so the memory conclusion may be wrong.

**Update — the real cause was in the logs and Anchor misread them.** Reading the previous container log manually shows:
- A fatal exception during **logging initialization at startup**: the stack runs through Spring Boot `LoggingApplicationListener.initialize` ← `onApplicationEnvironmentPreparedEvent` ← `SpringApplication.prepareEnvironment` ← `CbDataMartCheckingAccountAttritionApplication.main`. This happens before the application context and web server start, and Spring Boot exits with **code 1** when logging init fails. This matches the exit code; it is not an OOM.
- A related warning: log4j `MissingResourceException: Can't find resource for bundle java.util.PropertyResourceBundle, key log.level` while looking up ResourceBundle `[application]`. The log4j2 config likely uses `${bundle:application:log.level}` and that key is missing for the `uat-pci` profile.
- The exception header and its `Caused by` lines (which name the exact failure) are above the stack frames. Anchor never surfaced them; it was distracted by the JVM flags and Datadog tracer banner at the start of the log.
- Open question: if the app dies during logging init it never serves HTTP, so the startup-probe HTTP 500s may come from a different restart attempt. The eval should check this rather than assume.

**Expected:** Anchor reads the spilled log itself (grep for errors, read the tail), finds the actual startup error, and bases the RCA on it.

---

## 2. Investigate these likely causes (confirm each with code or logs)

### 2.1 The read-back tool is not callable by the model
- Is `read_spilled_output` in the tool list passed to `bind_tools` (or equivalent) for **every** agent call, including after any graph or tool-list rebuild?
- Does the name the model sees match **exactly** what the spill message tells it to call? The message says `anchor-main:read_spilled_output`. If the bound tool is `read_spilled_output` (or namespaced differently), the model can't call the name it was given.
- Is it filtered out by any read-only mode, tool allowlist or per-skill tool restriction? (The UI shows "READ ONLY MODE"; reading a local spill file is read-only and must stay allowed.)
- Check the run trace for investigation `7e60d31f…`: did the model ever attempt to call it, and was the call rejected?

### 2.2 The spill preview shows the wrong part of the output
- For logs, the failure is almost always at the **end**. The preview currently shows only the head.
- Check the preview length and whether the head is dominated by JVM/agent boilerplate.

### 2.3 Output is double-encoded
- Find where tool results are converted to text before spilling (e.g. `json.dumps` on something that is already a string or JSON text, or MCP content blocks serialized whole).
- Confirm by comparing the raw MCP response with the spilled file.

### 2.4 The run was allowed to finish with a doable follow-up
- Why did the gate/review let the agent finish while a check it could do itself was "Not attempted"?
- Was the step limit, gate round limit or token budget hit? Check the run's state at the end.

### 2.5 The model doesn't know how to read a Java/Spring log
- It concluded "memory limit or leak" without evidence of exit 137 / `OOMKilled`, and missed the first exception before exit.
- Check what the model actually received from the logs tool: was the exception header present, or buried in thousands of `at …` frames and agent banners?

### 2.6 The prompt does not forbid handing tool work to the user
- Check whether the system prompt says Anchor must run its own tools rather than asking the user to.

---

## 3. Fixes to implement (after confirming the causes)

1. **Tool availability and naming**
   - Ensure `read_spilled_output` is always bound and allowed in read-only mode.
   - Generate the spill message from the actual bound tool name, never a hardcoded string.
   - Add a startup check that every tool named in system messages or spill messages exists in the bound tool list.

2. **Better spill preview**
   - Preview = first ~20 lines + **last ~80 lines** + up to ~40 lines matching `ERROR|Exception|Caused by|FATAL|Fatal|panic|Traceback|exit code|OOMKilled|Killed`, each section labeled.
   - Keep the total preview under the existing preview size limit; trim the head first.
   - Add `tail` (last N lines) to `read_spilled_output` alongside `grep`, `offset` and `limit`.

3. **No double encoding**
   - If a tool result is a string, use it as-is. If it is JSON text, decode once. If it is MCP content blocks, join their `text` fields. Only `json.dumps` real objects.
   - Unescape before spilling so grep patterns match.

4. **Prompt rules** (add to `anchor_system_prompt.md`, evidence section)
   - "Never ask the user to run Anchor's own tools. If a tool output was spilled, read it yourself (grep for errors and read the tail) before concluding."
   - "For crashed or restarting pods, check the last termination reason and exit code before naming a cause. Exit code 137 / `OOMKilled` means memory; exit code 1 means the application exited with an error, so find that error in the logs."

5. **Log-reading rules** (add to the prompt)
   - "Find the FIRST exception before the container exited. Read its header line and every `Caused by:` line; skip the `at …` frames except the first few that name application classes."
   - "Treat JVM flags, agent/tracer startup banners and config dumps as noise unless an error references them."
   - "Tie the cause to the exit code: exit 1 → find the application exception; exit 137 / `OOMKilled` → memory. Never conclude OOM without 137 or `OOMKilled`."
   - "Quote the exact exception header and root `Caused by` line in the why-chain evidence."

6. **Deterministic exception extraction (code, before the model sees the log)**
   - Add a helper in `anchor-kube`'s log tool (or in the spill step) that parses logs and returns:
     - each distinct exception: header line, first 5 frames, and every `Caused by:` line with its first 3 frames, with repeats collapsed and counted
     - WARN/ERROR lines that are not stack frames
     - the last ~50 lines before the container exited
     - the container's last termination reason and exit code
   - Return this summary first, with the full log still spilled and readable via `read_spilled_output`.
   - Handle Java/Spring stacks first; keep the parser generic enough for Python tracebacks and Go panics.

7. **Gate/review**
   - Review question: "Is there any follow-up you could do with your own tools? If yes, add it as a task and continue."
   - In code: if the draft answer contains "Not attempted" (or a similar unresolved follow-up) and the run has steps left, treat it as an open task and loop back once.

8. **Token and time visibility (measure now, optimize later)**
   - We are still building, so token consumption is acceptable for now. **Do not trade accuracy for tokens in this change.**
   - Only add measurement: log input, output and reasoning tokens per model call, and latency per tool call, for each run. Show totals per investigation.
   - Defer optimizations (lower reasoning effort for tool-selection steps, shorter outputs, budgets) until evals are stable. Note candidate optimizations in the report but don't implement them.
   - The exception extraction in item 6 will cut input tokens as a side effect; that's fine.

---

## 4. Tests

- **Unit:** spill preview includes head, tail and error matches; labeled sections; size limit respected.
- **Unit:** stringify does not double-encode strings, JSON text or MCP content blocks.
- **Unit:** spill message tool name equals the bound tool name; startup check fails on a mismatch.
- **Unit:** exception extractor on this exact log returns the logging-init exception header and its `Caused by` chain, plus the `MissingResourceException` warning, and drops the JVM/tracer banner.
- **Unit:** `read_spilled_output` works in read-only mode and rejects paths outside the spill dir.
- **Eval:** add `usbinsights-cbbdmacctattr` crash as a case (use recorded logs; never change live systems). Pass = Anchor names the **logging initialization failure at startup** as the cause, quotes the exception header and root `Caused by` line, links it to exit code 1, mentions the missing `log.level` bundle key, and does not claim OOM. Fail = any memory/OOM conclusion, or asking the user to read the log.
- **Regression:** existing eval cases and simple questions behave the same or better.

## 5. Report back

- Which causes were confirmed and the evidence for each.
- What changed (files, functions).
- Eval results before and after, with tokens and time per run.
- Candidate token optimizations for later (not implemented).
- The actual root cause of the `usbinsights-cbbdmacctattr` crash once Anchor finds it.
