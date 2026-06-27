---
description: Analyze open GitHub issues for ROI × feasibility, cluster, and propose a prioritized plan
argument-hint: "[label or keyword, optional]"
---

Open issues (live):
!`env -u GH_TOKEN -u GITHUB_TOKEN gh issue list --state open --limit 100`

Analyze the open issues above for **ROI and feasibility**. If `$ARGUMENTS` is set, restrict to issues matching it (label or keyword).

Steps:

1. **Cluster** the issues by concern (e.g. HTTP/status-code semantics, `fetch()` features, sources/wrappers, docs, security).
2. **Assess each issue** — ROI (High/Med/Low), Effort (S < 0.5d / M 1–2d / L > 2d), risk/feasibility, and dependencies. Read issue bodies with `env -u GH_TOKEN -u GITHUB_TOKEN gh issue view <N>` and the relevant code where it matters; fan out a subagent per cluster (Task tool) to keep the main context clean.
3. **Synthesize** a master table sorted by priority (P0–P3) plus a recommended execution order. Flag the highest-ROI quick wins and any stale/close candidates.

Base effort estimates on the actual code — don't fabricate them. Verify any external/vendor claim against a first-party source before asserting it.
