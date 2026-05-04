---
name: gitnexus
description: "Query code intelligence via GitNexus MCP tools — execution flows, symbol impact, blast radius, refactoring, PR review, and debugging. Use when the user wants to understand architecture, assess change risk, debug code, or refactor safely. Examples: \"How does X work?\", \"What breaks if I change this?\", \"Is it safe to rename this?\", \"Review PR #42\""
version: 1.0.0
author: Hermes Agent (ported from GitNexus Claude Code skills)
license: MIT
metadata:
  hermes:
    tags: [code-intelligence, gitnexus, knowledge-graph, impact-analysis, debugging, refactoring, pr-review]
    related_skills: [codebase-inspection]
---

# GitNexus

Query a code knowledge graph via 7 MCP tools — understand architecture, trace execution flows, assess blast radius, debug, refactor, and review PRs.

## Quick Reference

**Always start here:**
1. `mcp_gitnexus_list_repos` → discover indexed repos
2. `mcp_gitnexus_read_resource` with `gitnexus://repo/{name}/context` → overview + check staleness
3. Match your task to a workflow below and follow it

> If the context resource says the index is stale, run `gitnexus analyze` in the terminal first.

## MCP Tools

| Tool | What it gives you |
|------|-------------------|
| `mcp_gitnexus_query` | Process-grouped code intelligence — execution flows related to a concept |
| `mcp_gitnexus_context` | 360-degree symbol view — callers, callees, processes it participates in |
| `mcp_gitnexus_impact` | Symbol blast radius — what breaks at depth 1/2/3 with confidence |
| `mcp_gitnexus_detect_changes` | Git-diff impact — what do your current changes affect |
| `mcp_gitnexus_rename` | Multi-file coordinated rename with confidence-tagged edits |
| `mcp_gitnexus_cypher` | Raw graph queries (read `gitnexus://repo/{name}/schema` first) |
| `mcp_gitnexus_list_repos` | Discover indexed repos |
| `mcp_gitnexus_read_resource` | Read lightweight graph resources (~100-500 tokens each) |

## Resources (via `mcp_gitnexus_read_resource`)

| URI | Content |
|-----|---------|
| `gitnexus://repo/{name}/context` | Stats, staleness check (~150 tokens) |
| `gitnexus://repo/{name}/clusters` | All functional areas with cohesion scores (~300 tokens) |
| `gitnexus://repo/{name}/cluster/{clusterName}` | Area members with file paths (~500 tokens) |
| `gitnexus://repo/{name}/processes` | All execution flows |
| `gitnexus://repo/{name}/process/{processName}` | Step-by-step execution trace (~200 tokens) |
| `gitnexus://repo/{name}/schema` | Graph schema for Cypher queries |

## Graph Schema

**Nodes:** File, Function, Class, Interface, Method, Community, Process
**Edges (CodeRelation.type):** CALLS, IMPORTS, EXTENDS, IMPLEMENTS, DEFINES, MEMBER_OF, STEP_IN_PROCESS

```cypher
MATCH (caller)-[:CodeRelation {type: 'CALLS'}]->(f:Function {name: "myFunc"})
RETURN caller.name, caller.filePath
```

---

## Workflows

### Exploring — "How does X work?"

**When:** "Explain the auth flow", "What calls this function?", "Show me the project structure"

```
1. mcp_gitnexus_read_resource(gitnexus://repo/{name}/context)  → overview + staleness
2. mcp_gitnexus_query({query: "<concept>"})                   → find execution flows
3. mcp_gitnexus_context({name: "<symbol>"})                  → callers/callees deep dive
4. mcp_gitnexus_read_resource(gitnexus://repo/{name}/process/{name})  → trace execution
```

**Checklist:**
- [ ] Read context resource
- [ ] Query for the concept
- [ ] Context on key symbols
- [ ] Trace execution flow via process resource
- [ ] Read source files for implementation

**Example:**
```
1. mcp_gitnexus_read_resource(uri: "gitnexus://repo/hermes-agent/context")
   → 2,757 files, 84,441 nodes, 300 processes

2. mcp_gitnexus_query({query: "telegram message handling"})
   → Processes: MessageFlow, TelegramPolling, CommandDispatch

3. mcp_gitnexus_context({name: "handleMessage"})
   → Incoming: telegram polling loop
   → Outgoing: parseMessage, dispatchCommand, sendResponse
```

---

### Impact Analysis — "What breaks if I change X?"

**When:** "Is it safe to change this?", "Show me the blast radius", "What depends on this?"

```
1. mcp_gitnexus_impact({target: "X", direction: "upstream"})  → map all dependents
2. mcp_gitnexus_read_resource(gitnexus://repo/{name}/processes) → check affected flows
3. mcp_gitnexus_detect_changes({scope: "staged"})             → map current git changes
4. Assess risk and report
```

**Checklist:**
- [ ] Run `mcp_gitnexus_impact` with direction: "upstream"
- [ ] Review d=1 items first (these WILL BREAK)
- [ ] Check high-confidence (>0.8) dependencies
- [ ] Check affected execution flows via process resource
- [ ] Run `detect_changes` for pre-commit check
- [ ] Assess risk level and report

**Understanding depth:**
| Depth | Risk | Meaning |
|-------|------|---------|
| d=1 | **WILL BREAK** | Direct callers/importers |
| d=2 | LIKELY AFFECTED | Indirect dependencies |
| d=3 | MAY NEED TESTING | Transitive effects |

**Risk levels:**
| Affected | Risk |
|----------|------|
| <5 symbols, few processes | LOW |
| 5-15 symbols, 2-5 processes | MEDIUM |
| >15 symbols or many processes | HIGH |
| Critical path (auth, payments) | CRITICAL |

---

### Debugging — "Why is X failing?"

**When:** "Trace where this error comes from", "Who calls this method?", "This endpoint returns 500"

```
1. mcp_gitnexus_query({query: "<error or symptom>"})   → find related flows
2. mcp_gitnexus_context({name: "<suspect>"})          → callers/callees
3. mcp_gitnexus_read_resource(gitnexus://repo/{name}/process/{name})  → trace flow
4. mcp_gitnexus_cypher({query: "MATCH path..."})      → custom traces if needed
```

**Checklist:**
- [ ] Understand the symptom
- [ ] Query for error text or related code
- [ ] Identify suspect from returned processes
- [ ] Context on suspect function
- [ ] Trace execution flow
- [ ] Read source files to confirm root cause

**Debugging patterns:**
| Symptom | Approach |
|---------|----------|
| Error message | `query` for error text → `context` on throw sites |
| Wrong return value | `context` on function → trace callees for data flow |
| Intermittent failure | `context` → look for external calls, async deps |
| Performance issue | `context` → find symbols with many callers (hot paths) |
| Recent regression | `detect_changes` to see what changed |

**Example:**
```
1. mcp_gitnexus_query({query: "payment validation error"})
   → Processes: CheckoutFlow, ErrorHandling

2. mcp_gitnexus_context({name: "validatePayment"})
   → Outgoing: verifyCard, fetchRates (external API!)

3. mcp_gitnexus_read_resource(uri: "gitnexus://repo/my-app/process/CheckoutFlow")
   → Step 3: validatePayment → fetchRates (external)

4. Root cause: fetchRates calls external API without proper timeout
```

---

### Refactoring — "Rename/extract/split safely"

**When:** "Rename this function", "Extract this into a module", "Split this service"

```
1. mcp_gitnexus_impact({target: "X", direction: "upstream"}) → map all dependents
2. mcp_gitnexus_query({query: "X"})                           → find execution flows
3. mcp_gitnexus_context({name: "X"})                          → all incoming/outgoing refs
4. Plan update order: interfaces → implementations → callers → tests
```

**Checklist:**
- [ ] Map all dependents with `mcp_gitnexus_impact`
- [ ] Review all callers/callees with `mcp_gitnexus_context`
- [ ] Plan update order
- [ ] Apply refactoring
- [ ] `mcp_gitnexus_detect_changes()` to verify scope
- [ ] Run tests for affected processes

**Symbol rename checklist:**
```
- [ ] mcp_gitnexus_rename({symbol_name: "oldName", new_name: "newName", dry_run: true}) — preview
- [ ] Review graph edits (high confidence) and ast_search edits (review carefully)
- [ ] If satisfied: mcp_gitnexus_rename({..., dry_run: false}) — apply
- [ ] mcp_gitnexus_detect_changes() — verify only expected files changed
- [ ] Run tests for affected processes
```

**Risk rules:**
| Risk Factor | Mitigation |
|-------------|-----------|
| Many callers (>5) | Use `mcp_gitnexus_rename` for automated updates |
| Cross-area refs | Use `detect_changes` after to verify scope |
| String/dynamic refs | `query` to find them |
| External/public API | Version and deprecate properly |

---

### PR Review — "Review PR #42"

**When:** "Review this PR", "Is this safe to merge?", "What's the blast radius?"

```
1. gh pr diff <number>                                  → get the raw diff
2. mcp_gitnexus_detect_changes({scope: "compare", base_ref: "main"})  → map diff to flows
3. For each changed symbol:
   mcp_gitnexus_impact({target: "<symbol>", direction: "upstream"})   → blast radius
4. mcp_gitnexus_context({name: "<key symbol>"})     → understand callers/callees
5. mcp_gitnexus_read_resource(gitnexus://repo/{name}/processes) → check affected flows
6. Summarize with risk assessment
```

**Checklist:**
- [ ] Fetch PR diff (`gh pr diff` or `git diff base...head`)
- [ ] `mcp_gitnexus_detect_changes` to map changes to affected flows
- [ ] `mcp_gitnexus_impact` on each non-trivial changed symbol
- [ ] Review d=1 items (WILL BREAK) — are callers updated?
- [ ] `mcp_gitnexus_context` on key changed symbols
- [ ] Check if affected processes have test coverage
- [ ] Assess overall risk level
- [ ] Write review summary

**Review dimensions:**
| Dimension | GitNexus Help |
|-----------|--------------|
| Correctness | `context` shows callers — are they all compatible? |
| Blast radius | `impact` shows d=1/d=2/d=3 dependents |
| Completeness | `detect_changes` shows all affected flows |
| Test coverage | `impact({includeTests: true})` |
| Breaking changes | d=1 upstream callers not in PR = potential breakage |

**Risk assessment:**
| Signal | Risk |
|--------|------|
| Changes touch <3 symbols, 0-1 processes | LOW |
| Changes touch 3-10 symbols, 2-5 processes | MEDIUM |
| Changes touch >10 symbols or many processes | HIGH |
| Changes touch auth, payments, or data integrity | CRITICAL |

**Example review output:**
```markdown
## PR Review: <title>

**Risk: MEDIUM**

### Changes Summary
- 3 symbols changed across 4 files
- 2 execution flows affected

### Findings
1. **[BUG]** webhookHandler calls validatePayment but not updated for new signature
2. **[BUG]** createPayment depends on PaymentInput type which changed
3. **[OK]** formatAmount change is backwards-compatible

### Missing Coverage
- webhookHandler not updated in PR (potential breakage)
- No test for webhook payment path

### Recommendation
REQUEST CHANGES
```

---

## CLI Commands (for setup/troubleshooting)

Run via `gitnexus` CLI (globally installed):

| Command | Purpose |
|---------|---------|
| `gitnexus analyze` | Build/refresh index (add `--skip-agents-md`) |
| `gitnexus analyze --embeddings` | Index with semantic search (slower) |
| `gitnexus status` | Check index freshness |
| `gitnexus clean` | Delete index and unregister repo |
| `gitnexus list` | List all indexed repos |
| `gitnexus wiki` | Generate docs from knowledge graph |

**Staleness:** If `gitnexus://repo/{name}/context` says the index is stale, run:
```bash
gitnexus analyze
```

**Durable config:** The global registry lives at `~/.gitnexus/registry.json`. To make it persistent:
```bash
GITNEXUS_HOME=/workspace/.gitnexus
```

The per-repo index (`.gitnexus/` inside each repo) is automatically durable if the repo is inside `/workspace`.

## Troubleshooting

- **"Index is stale"** → run `gitnexus analyze` in terminal
- **"No indexed repositories"** → `gitnexus analyze` from inside a git repo
- **"Not inside a git repository"** → run from a directory inside a git repo
- **Repo not found** → check `mcp_gitnexus_list_repos` for available repos
