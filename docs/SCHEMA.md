# Claude Code session log schema

Last inspected: November 12, 2026. Written for the parser prompt.

This document describes **structure only**: record types, field names, types, counts, and
token numbers. No prompt text, file contents, or tool output was copied here. Inspection
scripts printed key paths, JSON types, counts, and a small allowlist of enum-like values
(record types, tool names, model ids, stop reasons). They live outside the repo.

## 1. What was inspected

| Item | Count |
|---|---|
| Log files under `~/.claude/projects` | 1,003 |
| Top-level session files (`<sessionId>.jsonl`) | 83 |
| Subagent files (`<sessionId>/subagents/agent-<agentId>.jsonl`) | 49 |
| Workflow agent files (`.../subagents/workflows/wf_<id>/agent-<agentId>.jsonl`) | 764 |
| Workflow journals (`.../workflows/wf_<id>/journal.jsonl`) | 107 |

The detailed profile below uses the 83 top-level files: about 36,200 `assistant` records
collapsing to about 15,300 distinct API responses, and 19,400 `user` records. Subagent and
workflow files were checked separately (section 8).

**Limits of this sample.** One user, one machine, Claude Code versions 2.1.209 to 2.1.322,
entrypoints `claude-vscode` and `claude-desktop`. Fields appear and disappear across versions
(for example `requestRef` and the `api-request*` records exist only in newer ones). The parser
must treat every field except `type` as optional. Teammates on other versions, or on Codex or
Copilot, will differ. Counts drift by a few records because the live session was still being
written during inspection.

## 2. File layout

```
~/.claude/projects/<encoded-working-dir>/
    <sessionId>.jsonl                          one file per session, one JSON object per line
    <sessionId>/subagents/agent-<agentId>.jsonl
    <sessionId>/subagents/workflows/wf_<id>/agent-<agentId>.jsonl
    <sessionId>/subagents/workflows/wf_<id>/journal.jsonl
```

- `<encoded-working-dir>` is the session's working directory with path separators replaced
  by `-`. Some folders belong to scratch directories, not real projects.
- Every top-level file holds exactly one `sessionId`, and the file name equals it (83 of 83).
- No assistant `message.id` appears in more than one top-level file (0 of 15,314), so resumed
  or forked sessions did not duplicate responses in this sample.
- 0 lines failed to parse as JSON.

## 3. Record types

Every line is a JSON object with a `type`. Some `system` records also carry a `subtype`.
"Private" means the record holds prompt text, file contents, tool output, or account ids, and
must never be printed, logged, or copied.

| `type` | Count | What it is | Key fields | Private? |
|---|---|---|---|---|
| `assistant` | 36,213 | One content block of one model response | `message`, `uuid`, `parentUuid`, `requestId`, `requestRef`, `timestamp`, `sessionId`, `isSidechain`, `effort`, `thinkingDurationMs` | Yes (content blocks) |
| `user` | 19,368 | Human prompt, injected message, or a tool result | `message`, `uuid`, `parentUuid`, `toolUseResult`, `sourceToolAssistantUUID`, `promptId`, `isMeta`, `origin` | Yes |
| `api-request` | 10,866 | What was sent for one call: parameters plus hashes of the messages | `id`, `base`, `tail`, `keep`, `params`, `cacheControl`, `shapeHash`, `requestDigest` | Params no; see 9 |
| `api-request-blob` | 6,258 | Message bodies, stored once and keyed by hash | `hash`, `message` | Yes |
| `api-request-shape` | 133 | The system prompt and tool definitions of a request | `shapeHash`, `shape.system[]`, `shape.tools[]` | Yes (system prompt text) |
| `attachment` | 10,158 | Context the harness injected (reminders, listings, files) | `attachment.type`, `attachment.*`, `uuid`, `parentUuid` | Mostly yes |
| `cost-state` | 92 | Session-level token and cost totals per model | `modelUsage`, `totalCostUSD`, `totalAPIDuration`, `totalToolDuration`, `totalLinesAdded` | No |
| `system` | 276 | Harness events; `subtype` is `stop_hook_summary`, `local_command`, `api_error`, `compact_boundary`, `informational`, `model_refusal_fallback`, `model_refusal_no_fallback` | `subtype`, `level`, `timestamp`, `parentUuid` | Some have `content` |
| `queue-operation` | 3,366 | Prompts queued while the agent was busy | `operation` (`enqueue`, `dequeue`, `remove`), `reason`, `content` | Yes |
| `tools-used` | 190 | Names of tools used so far | `tools[]` | No |
| `last-prompt` | 8,059 | Pointer to the latest prompt | `lastPrompt`, `leafUuid` | Yes |
| `ai-title`, `custom-title`, `agent-name` | 4,204 / 642 / 315 | Session labels | `aiTitle`, `customTitle`, `agentName` | Yes |
| `file-history-snapshot`, `file-history-delta` | 352 / 1,264 | Undo backups of edited files | `messageId`, `trackingPath`, `backup` | Yes (paths) |
| `session-owner`, `bridge-session` | 2,332 / 947 | Account and remote-session ids | `accountUuid`, `organizationUuid`, `bridgeSessionId` | Yes (ids) |
| `pr-link` | 891 | Pull request opened from the session | `prNumber`, `prRepository`, `prUrl` | Yes |
| `mode`, `atis-latch` | 5,430 / 7,751 | Bookkeeping | `mode`, `atis` | No |

Records repeat (`last-prompt`, `session-owner`, `mode`, `ai-title` appear many times per
session), so counts of these are not counts of events.

## 4. The two records that matter

### 4.1 `assistant`

- **One record per content block, not per response.** `message.content` always has exactly one
  block. A response with thinking, text, and two tool calls becomes four records.
- Block `type` is one of `thinking`, `text`, `tool_use`, or (rarely) `fallback`.
- Records of the same response share `message.id`, `requestId`, and an identical `message.usage`
  (see 5). `apiBlockIndex` numbers the blocks 0..n-1 in file order for 11,576 of 12,260
  multi-block responses; do not rely on it.
- `message.model` is the model that answered. A synthetic model (`<synthetic>`, 6 records) marks
  locally generated error messages with no real usage.
- `message.stop_reason`: `tool_use`, `end_turn`, `refusal`, `stop_sequence`.
- Other useful fields: `timestamp`, `effort` and `perTurnEffort` (reasoning level),
  `thinkingDurationMs`, `message.usage.output_tokens_details.thinking_tokens`, `attributionSkill`
  and `attributionMcpServer` / `attributionMcpTool` (which skill or MCP tool the turn is
  attributed to), `isSidechain`, `agentId` (subagent files only).
- `message.diagnostics.cache_miss_reason.type` explains a cache miss when the harness knows:
  `previous_message_not_found`, `unavailable`, `model_changed`, `system_changed`,
  `tools_changed`, `messages_changed`.

### 4.2 `user`

Three kinds, told apart by `message.content`:

1. **Tool result.** `content` is a list whose block has `type: "tool_result"`, `tool_use_id`,
   `is_error`, and `content` (a string, or a list of `text` / `image` / `document` /
   `tool_reference` blocks). Exactly one result per record (18,250 of 18,250).
2. **Human prompt.** `content` is a string, or a list with `text` / `image` blocks. Newer
   versions add `origin.kind` (`human`, `task-notification`), `promptId`, and `permissionMode`.
3. **Injected.** `isMeta: true` (410), `isCompactSummary: true` (34, the summary written after
   a compaction), or `origin.kind: "task-notification"`.

`toolUseResult` is a structured copy of the result, shaped per tool (section 7). It is `obj`
(17,880), `str` (315), or `list` (43).

Tree structure: records link by `parentUuid`. It is a tree, not a line. Parallel tool calls
branch, and `compact_boundary` records have `parentUuid: null` plus `logicalParentUuid`.

## 5. Where token usage is recorded

**Level: per model call (API response).** Not per tool call, not per file, not per turn.

Every `assistant` record carries `message.usage`:

| Field | Meaning |
|---|---|
| `input_tokens` | Uncached input tokens |
| `cache_read_input_tokens` | Input served from cache |
| `cache_creation_input_tokens` | Input written to cache |
| `cache_creation.ephemeral_5m_input_tokens`, `.ephemeral_1h_input_tokens` | The cache-write split by TTL (they sum to the line above) |
| `output_tokens` | Output tokens, including thinking |
| `output_tokens_details.thinking_tokens` | The thinking part of `output_tokens` (34,256 records) |
| `server_tool_use.web_search_requests`, `.web_fetch_requests` | Server-side tool counts |
| `service_tier`, `speed`, `inference_geo` | Billing context |
| `iterations[]` | Per-iteration copy of the four counts above plus `type` and (sometimes) `model` |

All are **exact**, read from the log.

### The double-counting trap

Because each response is split into one record per block, **all records of a response repeat the
same usage**. In this sample: 12,260 responses span more than one record, and in all 12,260 the
four token counts are identical across their records. The parser must count usage **once per
`message.id`**.

### Reconciliation against `cost-state`

`cost-state` holds, per model: `inputTokens`, `outputTokens`, `cacheReadInputTokens`,
`cacheCreationInputTokens`, `thinkingTokens`, `webSearchRequests`, `costUSD`, plus session totals.
For each (session, model) entry in the last `cost-state` of a session (146 entries):

| Result | Entries |
|---|---|
| Equals the sum of usage over distinct `message.id` in the top-level file, exactly | 51 |
| Equals it only when that session's subagent and workflow files are added | 19 |
| Matches neither way (see open questions) | 76 |

So per-response deduplication is correct where it can be checked. `cost-state` is larger than
the transcript whenever calls exist that produce no `assistant` record. In 64 of the 146
entries the model has no `assistant` record at all in the top-level file (small helper-model
calls and subagent models).

`costUSD` is computed by the client at its own price table. It is exact in the sense that it is
read from the log, but it is not a bill. Label it **API-equivalent**.

### Other usage details

- `iterations[].type` is `message` (36,199) or `fallback_message` (4). A fallback appears to be a
  model refusal rerouting a call to another model (inferred from the field names, not
  confirmed); the `system/model_refusal_fallback` record names `originalModel` and
  `fallbackModel`. Whether top-level `usage` already includes the fallback
  iteration is not yet checked.
- `usage.iterations` is `null` for the 6 synthetic records.
- `message.input_transformations[]` (`type: thinking_dropped`, 781 records) records thinking
  blocks removed before sending. It affects what was billed as input, not the counts.

## 6. How a tool call links to its result

```
assistant record                       user record
  message.content[0].type = tool_use     message.content[0].type = tool_result
  message.content[0].id  ────────────►   message.content[0].tool_use_id
  uuid ◄────────────────────────────────  sourceToolAssistantUUID
                                          parentUuid (equal to sourceToolAssistantUUID)
```

Verified on 18,250 results: `tool_use_id` always resolves to an earlier `tool_use`, and
`sourceToolAssistantUUID` equals the `uuid` of the `assistant` record that holds that block in
all 18,250. Orphan results: 0. Calls with no result: 2.

- **Parallel calls.** A response can hold several `tool_use` blocks: 1 block in 12,691
  responses, 2 in 1,313, 3 in 364, up to 8 and more. Each block gets its own `assistant`
  record and its own `user` result record.
- **Ordering.** Join by id, never by file position. The join held for every result checked,
  but result order relative to the call order was not verified.
- **Response to request.** `assistant.requestRef` equals `api-request.id` (26,227 assistant
  records carry it). `assistant.requestId` is the API's request id and is shared by all blocks
  of a response; it does not match `api-request.id`.

## 7. What each tool call touched

`tool_use.name` and `tool_use.input` say what was touched. Counts below are calls across all
1,003 files.

| Tool | Calls | Touched | Input fields | Result (`toolUseResult`) fields |
|---|---|---|---|---|
| `Bash` | 39,683 | **Not structured.** Files, URLs, and searches exist only inside the `command` string | `command`, `description`, `timeout`, `run_in_background` | `stdout`, `stderr`, `interrupted`, `noOutputExpected`, `backgroundTaskId`, `persistedOutputPath`, `persistedOutputSize` |
| `Read` | 7,906 | File: `file_path`; range: `offset`, `limit` | `file_path`, `offset`, `limit` | `type` (`text`, `image`, `pdf`, `notebook`, `file_unchanged`), `file.filePath`, `file.content`, `file.numLines`, `file.startLine`, `file.totalLines`, `file.originalSize` (images), `file.truncatedByTokenCap` |
| `Edit` | 4,288 | File: `file_path` | `file_path`, `old_string`, `new_string`, `replace_all` | `filePath`, `structuredPatch`, `oldString`, `newString`, `userModified` |
| `Write` | 1,506 | File: `file_path` | `file_path`, `content` | `type`, `filePath`, `content`, `structuredPatch` |
| `NotebookEdit` | 7 | File: `notebook_path` | `notebook_path`, `cell_id`, `edit_mode` | `notebook_path`, `old_source`, `new_source` |
| `Grep` | 7 | Search: `pattern`; scope: `path`, `glob` | `pattern`, `path`, `glob`, `output_mode` | Not profiled (too few) |
| `WebFetch` | 561 | URL: `url` | `url`, `prompt` | `url`, `code`, `bytes`, `durationMs`, `result` |
| `WebSearch` | 172 | Search: `query` | `query`, `mode` | `query`, `results`, `searchCount`, `durationSeconds` |
| `Agent` | 55 | A subagent: `subagent_type`, `prompt` | `description`, `prompt`, `subagent_type`, `run_in_background` | `agentId`, `status`, `resolvedModel`, `outputFile`; sync runs also `totalTokens`, `totalDurationMs`, `totalToolUseCount` |
| `Workflow` | 113 | A scripted multi-agent run | `script` or `scriptPath` | `runId`, `workflowName`, `transcriptDir`, `taskId`, `status` |
| `Skill` | 91 | Skill: `skill` | `skill`, `args` | `commandName`, `success` |
| `ToolSearch` | 158 | Query for deferred tools | `query`, `max_results` | `matches`, `total_deferred_tools` |
| `mcp__<server>__<tool>` | 108 | Varies by tool (ids, ranges, urls, queries) | tool-specific | Often a list or string, not an object |
| `Monitor`, `TaskStop`, `AskUserQuestion`, `StructuredOutput`, `ReadNotifications`, `SendMessage`, `Artifact`, `ListAgents`, `SendUserFile` | small | n/a | n/a | n/a |

Two consequences for the parser:

1. **Searches mostly hide inside `Bash`.** In this sample `Grep` ran 7 times and `Glob` never,
   while `Bash` ran 39,683 times. A "searches" line in the receipt needs a rule that
   recognizes search commands (`grep`, `rg`, `find`, and so on) inside `command`, and the
   same for file reads done by `cat`, `sed`, `head`. That rule is a heuristic, so the result
   is **estimated**.
2. **Tool name case varies.** A lowercase `bash` appears 6 times. Match names case-insensitively.

## 8. Subagents and workflows

- Subagent and workflow-agent records have `isSidechain: true` and an `agentId`. Their
  `sessionId` equals the **parent** session id (24 of 24 checked), and `agentId` equals the id
  in the file name (24 of 24).
- Their usage is **not** in the parent file. It lives in the subagent file, and the parent's
  `Agent` tool result gives only `agentId` and, for synchronous runs, `totalTokens`
  (present in 1 of 49 results). Add subagent files to get a session's full usage (19 entries
  reconciled only this way).
- Workflow agents live under `workflows/wf_<id>/`. `journal.jsonl` has three record kinds:
  `launched`, `started` (`key`, `agentId`, `label`, `phase`), and `result` (`key`, `agentId`,
  `result`). The `Workflow` tool result names the folder through `transcriptDir`.
- Subagent files contain the same record types as top-level files, including `api-request`.

## 9. Context that costs tokens but is not a tool call

The first call of a session already carries a large prompt. Three places hold it:

- **`attachment` records.** `attachment.type` values seen, with counts: `total_tokens_reminder`
  (2,879), `deferred_tools_record` (1,275), `environment` (1,138), `silent_turn_reminder` (951),
  `batching_reminder_sent` (700), `edited_text_file` (439), `queued_command` (327),
  `remote_session_change` (235), `model` (234), `prompt_snapshot` (229), `deferred_tools_delta`
  (162), `date` (150), `task_reminder` (131), `instructions` (130), `mcp_instructions_delta`
  (123), `agent_listing_delta` (118), `skill_listing` (118), `session_context` (116),
  `credential_org` (115), `ultra_effort_enter` (113), `file` (98), `skill_mention` (95),
  `command_permissions` (91), `compact_file_reference` (67), `auto_mode` (55),
  `invoked_skills` (31), `thinking_drop` (30), and a few rarer ones. The biggest by record size
  are `instructions` (median about 61,000 characters, which carries the project instruction
  files), `skill_listing` (about 37,000), `invoked_skills` (about 37,000), `deferred_tools_delta`
  (about 27,000), `mcp_instructions_delta` (about 22,000), and `prompt_snapshot` (about 19,000).
  `file` is a file the harness attached on its own, with `filename`, `content`, `displayPath`.
- **`api-request-shape`.** The system prompt (`shape.system[]`) and the tool definitions
  (`shape.tools[]`, about 18 per record; each has `description` and `input_schema`).
- **`api-request` plus `api-request-blob`.** A compact log of each request. `params` holds
  `model`, `max_tokens`, `output_config.effort`, `thinking`, `betas`, `context_management`.
  `base` (10,765 of 10,866) is the `id` of an earlier `api-request`, so requests form a delta
  chain. `tail` is a list of hashes of the messages added since `base`; only 8,253 of 26,426
  tail hashes resolve to an `api-request-blob` in the same file, so the rest cannot be
  resolved from the log alone. `cacheControl` lists where cache breakpoints sat (`ttl`,
  `scope`).

## 10. What is missing for a per-step cost breakdown

| Need | What the log gives | Status |
|---|---|---|
| Tokens per model call | `message.usage`, once per `message.id` | **Exact** |
| Cost per model call | Tokens times a price table | Tokens exact; dollars are **API-equivalent**, from our own price table |
| Tokens per tool result | **Not recorded** | Must be **estimated** (below) |
| Tokens per file read, search, or fetch | **Not recorded** | **Estimated** |
| Split of one response's `output_tokens` between thinking, text, and tool-call arguments | Only the thinking total (`thinking_tokens`) | Thinking exact in total; text vs tool-call split **estimated** |
| Tokens of the system prompt, tool definitions, and project instructions | Only the sizes of the first call's prompt | Estimate from the first call, or from record characters |
| Which of several parallel results caused which tokens | Growth covers all of them together | Split by result size, **estimated** |
| Files and searches inside `Bash` | Only the `command` string | Heuristic parsing, **estimated** |
| Subagent usage inside the parent | Separate files | Exact, but the parser must walk the folder |
| Calls from helper models (for example title generation) | Only in `cost-state` totals | Exact in total, not attributable to a step |
| Per-call wall time | `timestamp` on every record; `thinkingDurationMs`; `cost-state.totalToolDuration` for the session | Approximate |

### Estimating tokens per tool result: the growth method

Total prompt size of call *n* is `input_tokens + cache_read_input_tokens +
cache_creation_input_tokens`. The growth from call *n* to call *n+1*, minus call *n*'s
`output_tokens`, is the tokens added by the tool result (plus any injected reminders).

Checked on consecutive same-model calls that made exactly one tool call and got its result:

| Tool | Pairs | Pearson r: result length in characters vs token growth |
|---|---|---|
| `Bash` | 10,476 | 0.964 |
| `Read` | 489 | 0.995 |
| `Edit` | 679 | 0.149 |
| `Write` | 526 | 0.102 |

Growth tracks result size closely for `Bash` and `Read`. `Edit` and `Write` correlate weakly
because their model-facing results are short and nearly constant, so there is little to
correlate. Growth also includes wrapper text and injected reminders, so the median
characters-per-token from this method (about 2.2 to 2.4) is lower than for plain text. Treat
growth as an **upper bound** for the result's own tokens. 16 of 12,683 pairs had negative
growth, which means context was cleared or compacted between calls; skip those.

## 11. Parser traps (all verified above)

1. Count usage once per `message.id`, not per record.
2. Join results by `tool_use_id`, not by file order. One result per `user` record.
3. Subagent and workflow usage sits in separate files under `<sessionId>/subagents/`.
4. Skip `<synthetic>` model records and `isApiErrorMessage` records when summing usage.
5. Every field except `type` can be missing. Several keys inside `message.content[].input`
   and `toolUseResult` vary by tool and version.
6. Dictionary keys can be data. `wireToolInputs` is keyed by tool-use id, and some tool inputs
   carry arbitrary key names. Never print or copy keys from `input` or `toolUseResult`.
7. Large records exist (median `instructions` attachment about 61,000 characters; sessions
   up to about 50 MB). Stream line by line.
8. Redact `session-owner`, `bridge-session`, and `pr-link` fields before any export.

## 12. Open questions

1. **The 76 unreconciled (session, model) entries.** `cost-state` exceeds the deduplicated
   transcript even after adding subagent and workflow files. Is the gap helper-model calls,
   workflows launched from other sessions, resumed sessions, or something else?
2. **Is `cost-state` cumulative or per segment?** 10 of 83 sessions have more than one
   `cost-state` record. Taking the last one worked for the exact matches, but the reset
   behavior is unconfirmed.
3. **Does top-level `usage` include `fallback_message` iterations?** Only 4 cases. Needed to
   avoid under- or over-counting after a refusal fallback.
4. **Can `tail` hashes be resolved?** Only about 31% match a blob in the same file. If the rest
   are the transcript's own `assistant` and `user` records, the full request could be rebuilt,
   which would give exact per-message sizes. How the hash is computed is unknown.
5. **Do Codex and Copilot logs record anything like this?** Unknown. The plan's open question
   about which agent teammates use decides whether the parser needs a second format.
6. **Does `Read` of an unchanged file (`type: file_unchanged`) cost tokens?** Only 3 cases, and
   it needs a check against growth.
7. **Which attachments sit in the first call versus later?** Needed to price the fixed
   overhead (instructions, skill listing, tool definitions) separately from the task itself.
8. **Will the log still hold per-call usage if a teammate's session is resumed or compacted?**
   `compact_boundary` and `isCompactSummary` records exist, but a compaction run was not
   traced end to end.
