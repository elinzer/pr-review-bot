# PR Review Bot — Project Context

## What this project is

A lightweight, single-user automation that auto-reviews GitHub PRs requesting the operator's team. Reviews are created as **pending reviews under the operator's GitHub account** (never posted publicly) so the operator inspects, edits, and submits via GitHub's native UI. Operator: el.linzer@spothero.com.

## Current status

**Design phase complete.** The full design spec lives at:

`docs/superpowers/specs/2026-05-22-pr-review-automation-design.md`

That spec was produced through the `superpowers:brainstorming` skill with the user. The user has approved the spec. **The next step is to invoke the `superpowers:writing-plans` skill to convert the spec into a step-by-step implementation plan.**

No code has been written yet. Only the spec and this CLAUDE.md exist.

## Locked design decisions (do not relitigate without explicit user reopen)

These were decided during brainstorming. Read the spec for full rationale.

- **Architecture:** Architecture A — local scheduled poller on macOS via launchd. Rejected: GitHub Actions (B) and Gmail-triggered (C).
- **Trigger:** Polls GitHub REST every 5 minutes (configurable). No webhooks, no Actions, no email.
- **Model:** Claude Opus 4.7 for *both* the review pass and the self-critique pass. Simplicity over cost optimization. Model is configurable via `MODEL` env var.
- **Scope of review:** Bugs and breaks only (correctness issues provable from the diff). **Style consistency was explicitly dropped** — too hallucination-prone.
- **Severities:** Two only — `bug` (asserted defect) and `question` (clarification, no assertion). No `style`.
- **Delivery:** GitHub pending review created via operator's PAT. The operator submits/discards via the GitHub UI.
- **Language:** Python. Operator works in a Django shop; Anthropic SDK + `PyGithub` are mature.
- **Modules:** 6 — `config`, `state`, `github_client`, `jira_client`, `prompt`, `reviewer`, plus `poller.py` orchestrator.
- **Jira:** Optional context. Missing ticket is INFO-logged, review proceeds without it. Uses Jira REST API with `JIRA_API_TOKEN` (NOT the Atlassian MCP — MCPs don't work from standalone scripts).
- **Cap:** 5 comments per PR maximum.
- **Anti-hallucination:** 6-layer defense (prompt rules, structured JSON output, self-critique pass, programmatic validation, conservative caps, operator as final filter). Validation layer is the highest-value test target.
- **Rollout:** 3 phases — DRY_RUN week, then pending-but-discarded week, then normal use.

## User preferences relevant to this project

From the operator's global `~/.claude/CLAUDE.md`:
- **Top-level imports only.** Never runtime/local imports inside function bodies.
- **No comments in code unless critical.** Skip if the code is obvious.
- **Don't run tests unless asked.**
- **PR descriptions:** if asked to write one, output as text — don't open a PR.
- **Teaching approach:** explain the "why" behind suggestions and walk through the reasoning, unless directly asked to just do something.
- **Jira lookups:** for read-only Jira queries during *this conversation*, use the Atlassian MCP (`mcp__claude_ai_Atlassian__getJiraIssue` with `cloudId=spothero.atlassian.net`). This is separate from the bot itself, which uses Jira REST.

## What to do next

When the user is ready to continue, invoke the `superpowers:writing-plans` skill and feed it the spec at `docs/superpowers/specs/2026-05-22-pr-review-automation-design.md`. The writing-plans skill will produce an implementation plan with review checkpoints; the user has already opted into the superpowers-style workflow.

If the user wants to revisit a design decision before implementation, that's fine — just be explicit about reopening the brainstorm rather than silently mutating the spec.
