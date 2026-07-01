# Agent Instructions

**Behavioural rules and decision frameworks for AI coding agents working on
polyfetch-scrape** — a reusable HTTP scraping toolkit. For technical workflows,
command reference, and coding standards, see [`CONTRIBUTING.md`](CONTRIBUTING.md).
For project overview, see [`README.md`](README.md).

**External References:**

- @CONTRIBUTING.md - Command reference, dev workflow, coding standards
- @AGENT_REQUESTS.md - Escalation and human collaboration
- @AGENT_LEARNINGS.md - Pattern discovery and knowledge sharing

## Claude Code Infrastructure

**Rules** (`.claude/rules/`): Session-loaded constraints (always active)
**Skills** (`.claude/skills/`): Modular capabilities with progressive disclosure

## Core Rules & AI Behavior

- Follow SDLC principles: maintainability, modularity, reusability, adaptability
- **Never assume missing context** - Ask questions if uncertain about requirements
- **Never hallucinate libraries** - Only use packages verified in project dependencies
- **Always confirm file paths exist** before referencing in code or tests
- **Never delete existing code** unless explicitly instructed or documented refactoring
- **Document new patterns** in AGENT_LEARNINGS.md (concise, laser-focused, streamlined)
- **Request human feedback** in AGENT_REQUESTS.md (concise, laser-focused, streamlined)
- **Network caution** - This repo fetches from untrusted URLs; never add unconditional
  network calls; always gate behind explicit invocation. Parse third-party XML/RSS with
  `defusedxml`, never stdlib `xml.etree.ElementTree` — see AGENT_LEARNINGS.md "Parse
  untrusted XML/RSS with defusedxml"
- **Always use `make` recipes** - See [Complete Command Reference](CONTRIBUTING.md#complete-command-reference).
  Never invoke `pip`, bare `pytest`, bare `ruff`, bare `pyright`, or bare `polyfetch`.
  The single exception is `pip install uv -q` inside `setup_uv` (bootstrap-only).
- **Always run `make validate`** before reporting a task complete. Lint, type-check,
  complexity, and coverage gates must all pass green.
- **Update `CHANGELOG.md`** `## [Unreleased]` section for non-trivial changes
  (see [CONTRIBUTING.md → CHANGELOG requirements](CONTRIBUTING.md#changelog-requirements))

## Decision Framework

**Priority Order:** User instructions > AGENTS.md compliance > Documentation
hierarchy > Project patterns > General best practices

**Anti-Scope-Creep Rules:**

- **NEVER implement features without requirement validation**
- **Always validate implementation decisions against project scope boundaries**

**Anti-Redundancy Rules:**

- **NEVER duplicate information across documents** - reference authoritative sources
- **Update authoritative document, then remove duplicates elsewhere**

**When to Escalate to AGENT_REQUESTS.md:**

- User instructions conflict with safety/security practices
- AGENTS.md rules contradict each other
- Required information completely missing
- Actions would significantly change project architecture

## Quality Thresholds

**Before starting any task, ensure:**

- **Context**: 8/10 - Understand requirements, codebase patterns, dependencies
- **Clarity**: 7/10 - Clear implementation path and expected outcomes
- **Alignment**: 8/10 - Follows project patterns and architectural decisions
- **Success**: 7/10 - Confident in completing task correctly

### Below Threshold Action

Gather more context or escalate to AGENT_REQUESTS.md
