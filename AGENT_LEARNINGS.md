---
title: Agent Learning Documentation
description: Non-obvious patterns that prevent repeated mistakes across sprints
---

## Template

- **Context**: When/where this applies
- **Problem**: What issue this solves
- **Solution**: Implementation approach
- **Example**: Working code
- **References**: Related files

## Learned Patterns

### Verify single-subagent claims before propagating

- **Context**: Spawning a subagent (Task tool, or any nested agent) to gather facts about external vendors, products, or third-party code that the subagent cannot fetch directly.
- **Problem**: Subagents without web access fabricate plausible-but-wrong specifics from training data. Observed twice in one session: "BIQU Hurakan belt mod" and "White Knight by Annex Engineering" — both confidently asserted, both wrong on first-party verification.
- **Solution**: Treat any single-subagent vendor/product/library attribution as a hypothesis until a first-party source (vendor site, official docs, package registry, gh API) confirms it. Verify *before* threading the claim into a PR, issue body, or documentation. The verification step is cheap; the propagation cost is high once the fabrication is in code review or the changelog.
- **Example**: When a subagent returns "Library X, by Author Y, MIT license, used by Project Z", before quoting any of those, fetch the project's actual README / PyPI page / repo. If any of the four facts is wrong, all four are suspect.
- **References**: This learning has no in-tree code reference — it is a workflow rule. Compound-learning promotion path: stays in `AGENT_LEARNINGS.md` until a second occurrence justifies promoting to `.claude/rules/`.
