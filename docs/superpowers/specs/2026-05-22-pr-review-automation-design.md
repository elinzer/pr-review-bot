# PR Review Automation — Design

**Date:** 2026-05-22
**Author:** el.linzer@spothero.com
**Status:** Design approved, pre-implementation

---

## 1. Overview

A lightweight, single-user automation that reviews GitHub pull requests where a designated team is a requested reviewer. The reviewer drafts comments as a GitHub **pending review** under the operator's user account, so the operator inspects, edits, and submits via GitHub's native UI before anything becomes visible to teammates.

Built for one person's workflow: runs locally on macOS, no shared infrastructure, no org-wide deploy.

## 2. Goals

- Auto-detect new PRs requesting the operator's team for review.
- Produce a high-precision review focused on **bugs and breaks** (correctness issues provable from the diff).
- Deliver the review as a **pending** review on GitHub under the operator's account, never as a bot or public comment.
- Minimize hallucinations through layered guardrails — prefer silence to speculation.
- Stay simple: ~6 Python modules, one JSON state file, one launchd plist.

## 3. Non-goals

- Style consistency commentary. Dropped from scope — too hallucination-prone, requires repo-wide context the bot can't reliably acquire.
- Multi-user support. This is one person's tool.
- Web UI or dashboard. Logs and state files only.
- Running when the operator's laptop is closed. Acceptable trade-off for simplicity.
- Auto-submitting reviews. The pending-review handoff is the design.

## 4. Architecture

**Pattern:** Local scheduled poller on macOS.

```
launchd (every 3 min)
    │
    ▼
poller.py ──► github_client (list team review-requests)
    │
    │  for each new PR:
    │
    ├──► github_client.get_pr_context()      # diff, files, body
    ├──► jira_client.fetch_ticket()           # optional context
    ├──► reviewer.review()                    # Claude call → JSON review
    ├──► reviewer.self_critique()             # Claude audits its own output
    ├──► reviewer.validate()                  # programmatic safety net
    └──► github_client.create_pending_review()  # uses operator's PAT
         │
         ▼
    state.json (mark reviewed)
```

**Why local poller** (vs GitHub Actions or hosted webhook):
- Zero org-side changes, no secrets in shared infra.
- Operator's PAT stays on their machine.
- Iteration on prompts is a local file edit, no redeploy.
- Migration path: review logic is decoupled from trigger, so swapping to Actions later means rewriting only `poller.py`.

## 5. Components

```
pr-review-bot/
├── pr_review/
│   ├── __init__.py
│   ├── config.py         # loads .env into a typed Config object
│   ├── state.py          # JSON-backed dedup of already-reviewed PRs
│   ├── github_client.py  # list team review-requests, fetch context, create pending review
│   ├── jira_client.py    # extract ticket key, fetch via Atlassian REST
│   ├── prompt.py         # prompt templates with anti-hallucination rules
│   ├── reviewer.py       # build → call → self-critique → validate → Review
│   └── poller.py         # orchestrates one poll cycle; module entry point
├── tests/
├── .env.example
├── .gitignore            # ignores .env, state.json, *.log
├── pyproject.toml
├── README.md
└── com.elinzer.pr-review-bot.plist  # launchd template
```

Each module has one job. Each is independently testable. Prompt iteration touches only `prompt.py`; auth changes touch only `github_client.py`; etc.

## 6. Data flow (per poll cycle)

1. launchd invokes `python -m pr_review.poller`.
2. `poller` loads `Config` from `.env`.
3. `poller` calls `github_client.list_team_review_requests(team_slug)`.
   - Uses GitHub REST: search issues for `is:pr is:open review-requested:<team>`.
   - Returns a list of `PullRequest` summaries.
4. `poller` filters via `state.unreviewed(prs)`. Reviewed PRs are skipped.
5. For each unreviewed PR:
   - `github_client.get_pr_context(pr)` → diff, changed files (path + content), PR body, branch name.
   - `jira_client.fetch_ticket(extract_key(pr.body, pr.branch))` → ticket title, description, acceptance criteria. **Optional** — missing ticket is logged at INFO and the review proceeds without it.
   - `reviewer.review(pr_context, jira_context)` → calls Claude Opus 4.7, returns a `Review` (summary + list of `Comment`).
   - `reviewer.self_critique(review, pr_context)` → second Opus call audits each comment, returns a list of indices to keep.
   - `reviewer.validate(filtered_review, pr_context)` → programmatic checks; drops anything that fails.
   - `github_client.create_pending_review(pr, validated_review)` → POSTs to GitHub REST using operator's PAT.
   - `state.mark_reviewed(pr.url, review_id)`.
6. Errors per PR are logged and isolated — one bad PR doesn't poison the rest of the cycle.

**Idempotency invariant:** a PR is marked reviewed in `state.json` *only after* the pending review is successfully created. Any crash before that point is safe to retry.

## 7. Anti-hallucination guardrails

Layered defense. Each layer assumes the previous one is imperfect.

### Layer 1 — Prompt rules

- **Citation required.** Every comment must include `evidence` with `quoted_code` (verbatim from the diff) and `citation` (`path:line-line`).
- **Diff-only scope.** Only comment on issues provable from the diff itself. If a claim depends on code not shown, downgrade to a `question` rather than asserting.
- **Silence over speculation.** Explicit instruction: "Output an empty comments array if nothing is high-confidence. We prefer missing a real bug to inventing one."

### Layer 2 — Structured output (JSON)

The model returns JSON conforming to:

```json
{
  "summary": "string, 1-3 sentences",
  "comments": [
    {
      "file": "path/from/diff",
      "line": 42,
      "severity": "bug" | "question",
      "body": "the comment",
      "evidence": {
        "quoted_code": "verbatim from diff",
        "citation": "path:40-44"
      }
    }
  ]
}
```

Two severities only. `bug` asserts a defect; `question` asks for clarification without asserting.

### Layer 3 — Self-critique pass

After the first call, send the draft back to Opus with a fresh system prompt:

> "You are auditing the review below. For each comment, verify that `evidence.quoted_code` appears verbatim in the diff context provided, and that the claim follows from the evidence. Output `{ keep: [indices], drop: [{index, reason}] }`."

Catches the "model invented the quote" failure that prompt rules alone miss.

### Layer 4 — Programmatic validation

Code, not the model, enforces:

- `comment.file ∈ pr.changed_files` (drop if not).
- `comment.line` falls inside an actual diff hunk (drop if not).
- `evidence.quoted_code` appears verbatim as a substring of the diff (drop if not).

Anything surviving all four layers is verifiable by construction.

### Layer 5 — Conservative defaults

- Hard cap: **5 comments per PR**. Forces prioritization.
- If 0 comments survive, post only the summary: "Reviewed; nothing high-confidence to flag." Honest signal.

### Layer 6 — The operator

Pending-review delivery is the final safety net. Anything that slipped through layers 1-5, the operator catches before submitting.

### Honest limits

- "Zero hallucinations" is aspirational. Layers 1-5 will achieve very high precision (~95%+ on surviving comments) but never zero. Layer 6 is load-bearing.
- These guardrails reduce **recall**: the bot will miss real issues it's not confident about. That's the intended trade-off given the precision priority.

## 8. Configuration

Single `.env` file at project root, `chmod 600`, never committed.

```
GITHUB_PAT=ghp_xxx
ANTHROPIC_API_KEY=sk-ant-xxx
JIRA_EMAIL=el.linzer@spothero.com
JIRA_API_TOKEN=xxx
GITHUB_TEAM_SLUG=spothero/<team-slug>
POLL_INTERVAL_SECONDS=180
MODEL=claude-opus-4-7
DRY_RUN=false
```

**PAT scope minimization:** fine-grained PAT, scoped only to the repos the team reviews. Required permissions: `pull_requests: read+write`, `contents: read`. Classic PATs are prohibited by design (too broad).

**Future hardening:** migrate secrets to macOS Keychain via the `keyring` library. Out of scope for v1.

## 9. Scheduling (launchd)

`~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist`:

- `RunAtLoad: true` — survives reboots.
- `StartInterval: 180` — runs every poll interval.
- Does not run while the laptop is asleep (no thundering herd on wake).
- `StandardOutPath` / `StandardErrorPath` → `~/Library/Logs/pr-review-bot/{stdout,stderr}.log`.

Operator controls:

- Pause: `launchctl unload ~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist`
- Resume: `launchctl load ~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist`
- One-shot test: `python -m pr_review.poller`

## 10. Error handling

| Failure | Response |
|---|---|
| GitHub rate limit | Backoff; skip remaining PRs this cycle; retry next interval |
| Anthropic rate limit / 5xx | Same — backoff, skip, retry next interval |
| Network error fetching PR context | Log; skip PR; not marked reviewed → retried next cycle |
| Claude returns malformed JSON | Increment `parse_failed` counter in state; after 3 fails, mark `skipped_manual` and stop retrying that PR |
| Missing Jira ticket | Log at INFO; proceed without Jira context |
| PAT invalid / 401 | Log loudly to stderr; do not retry; needs human intervention |
| Pending review already exists | Skip — state.json should prevent this; defense in depth |

## 11. Testing

- **Unit tests (`pytest`):**
  - `state.py` — JSON read/write, dedup.
  - `prompt.py` — template rendering against fixture inputs.
  - `reviewer.validate()` — handcrafted bad outputs (file not in diff, quote not found, line outside hunk). **These are the highest-value tests** because validate is the safety net.
  - `jira_client` — ticket key extraction regex against fixtures (branch names, body text).
- **Integration tests** (gated by env var, opt-in):
  - `github_client` against a private throwaway repo with one open PR.
  - End-to-end with `DRY_RUN=true` against a known PR; verify the full pipeline produces sane output without posting.
- **No tests for `poller.py`** — thin orchestration glue.

## 12. Rollout plan

Three phases to build confidence before letting the bot touch real PRs.

1. **Phase 1 — `DRY_RUN=true` for one week.** Bot runs on schedule, logs what it *would* post. Operator spot-checks against the actual PRs.
2. **Phase 2 — Pending reviews enabled, all discarded.** Bot creates real pending reviews; operator reads each one, discards all. Validates the GitHub UX without affecting teammates.
3. **Phase 3 — Normal use.** Operator submits the good ones, edits or discards the rest.

## 13. Open questions

- Operator's specific GitHub team slug to fill into `.env` at install.
- Whether the operator wants a `notify_on_review` hook (Slack DM, macOS notification) when a new pending review lands. **Default: no notification** — operator checks GitHub on their own cadence. Add later if desired.
- Whether to whitelist/blacklist specific repos. **Default: review every PR requesting the team across all accessible repos.** Add filtering later if noisy.

## 14. Out of scope

- Style and convention commentary (intentionally dropped).
- Cross-repo or repo-wide context (would require indexing).
- Multi-user / team-shared deployment.
- Web UI, dashboard, or metrics surface.
- Auto-submission of reviews.
- Slack-reaction-based approval workflow.
