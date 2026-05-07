# Codespaces auth: env-var precedence and plaintext reality

This project's `.devcontainer/devcontainer.json` maps the Codespaces user secret `GH_PAT` into both `GH_PAT` and `GH_TOKEN` env vars. This page documents *why*, what the precedence is for the tools we use, and where tokens land in plaintext.

## Required PAT scopes by operation

Use a fine-grained PAT (preferred) or classic PAT with the following minimum permissions for the operations this project performs:

| Operation | Fine-grained permission | Classic scope |
|---|---|---|
| `git clone` / `git fetch` (public repo) | (none required) | (none) |
| `git clone` / `git fetch` (private repo) | Contents: Read | `repo` |
| `git push` to your repo | Contents: Read and write | `repo` |
| `gh pr create` / `gh pr view` | Pull requests: Read | `repo` |
| `gh pr merge` (any strategy) | Pull requests: Read and write | `repo` |
| `gh pr merge --admin` (bypass branch protection) | + Administration: Write | `repo` + admin on the repo |
| `gh repo fork` | Administration: Read and write | `repo` (or `public_repo` for public targets) |
| `gh issue create` / comment | Issues: Read and write | `repo` |
| `gh release create` / asset upload | Contents: Read and write | `repo` |
| `gh workflow run` (manual dispatch) | Actions: Read and write | `workflow` |

For fine-grained PATs, **the repo must be explicitly selected** in the token's "Repository access" list; "All repositories" works but is broader than necessary. The classic `repo` scope is a single boolean that grants write to all your repos — fine-grained is recommended for blast-radius reasons.

If `gh pr merge` returns `Resource not accessible by integration`, the PAT lacks `Pull requests: write`. If `git push` returns `Permission to ... denied`, the PAT lacks `Contents: write` for that specific repo (or that repo isn't in the fine-grained PAT's allowed list).

## Tool-by-tool token precedence

The first source that resolves wins; later sources are ignored.

| Tool | Precedence order |
|---|---|
| `gh` CLI | `GH_TOKEN` → `GITHUB_TOKEN` → stored config (`~/.config/gh/hosts.yml`) |
| `git` push/fetch | `credential.helper` (in Codespaces: `/.codespaces/bin/gitcredential_github.sh`). Env vars are **not** read directly. |
| `git` over HTTPS, no helper | URL-embedded `https://x-access-token:TOKEN@github.com/...` (one-shot) |
| GitHub Actions runner | `${{ secrets.GITHUB_TOKEN }}` injected by runner; lifecycle ≠ Codespaces |

### Implications

- Setting `GH_TOKEN=$GH_PAT` makes `gh pr merge` use `$GH_PAT` regardless of what's in `hosts.yml` or `GITHUB_TOKEN`.
- Setting `GH_TOKEN` does **not** affect `git push` — the credential helper short-circuits before env vars matter. To make `git push` use `$GH_PAT`, either:
  - register `gh` as the credential helper: `gh auth setup-git` (writes a config that delegates to `gh`'s stored token, which adds a *second* plaintext copy of the token to `~/.config/gh/hosts.yml`); or
  - bypass the helper for one push: `git -c credential.helper= push "https://x-access-token:$GH_PAT@github.com/..."`.

## Where tokens are plaintext

Both at-rest on GitHub's side and in transit, secrets are encrypted (libsodium sealed boxes for storage, TLS for transit). Inside the running container, by contrast:

| Surface | Plaintext? | Notes |
|---|---|---|
| `/proc/<pid>/environ` | **yes** | Every env var on every process. `containerEnv` mapping puts `$GH_PAT` here. Visible to any process running as the same UID. |
| `~/.config/gh/hosts.yml` | **yes by default** | `gh auth login --with-token` writes the token plaintext unless a system keyring (`secret-service`, `gnome-keyring`, `kwallet`, macOS Keychain) is available. Default Codespaces images run no such service. |
| `.git-credentials` | yes | If you use `git config credential.helper store`. We do not. |
| Codespaces user secret on GitHub.com | **no** (sealed-box encrypted) | Decrypted only at codespace boot, then injected as env var (= back to plaintext in `/proc`). |
| TLS to api.github.com | **no** (TLS) | Standard transit encryption. |

## Mitigations and their limitations

| Mitigation | Helps with | Limitation |
|---|---|---|
| Run a `secret-service` daemon + use `gh`'s keyring backend | Encrypts `hosts.yml` at rest | Doesn't help `/proc/*/environ`. Adds a daemon + package install. Not standard in default Codespaces image. |
| `pass` (gpg-encrypted password store) | Same | Same; also needs a working gpg key, which Codespaces gh-gpgsign currently fails on (qte77/polyforge-orchestrator#64). |
| `git credential.helper=cache --timeout=300` | Removes on-disk plaintext for git | In-memory plaintext during cache; 5-min lifetime. Doesn't replace the Codespaces helper. |
| Device-flow login per session (`gh auth login --web`) | No long-lived secret in env | Manual interactive step on every codespace rebuild. |
| **Env-only (this project's choice)** | One source of truth; no extra plaintext copy | `/proc/*/environ` exposure is what it is — same blast radius as any other env var |

## Why this project sticks with env-only

Adding `gh auth login --with-token` to a `postCreateCommand` would *write a second plaintext copy* of `$GH_PAT` to `~/.config/gh/hosts.yml` without removing the first (the env var). That's strictly worse than env-only unless a keyring service is also installed.

If/when the qte77 baseline devcontainer adds a keyring service, the trade-off changes and this project should follow.

## GPG signing in Codespaces (gh-gpgsign)

Codespaces ships an opt-in GPG signing helper at `/.codespaces/bin/gh-gpgsign` that signs commits via the Codespaces identity service. When working, every agent commit in this codespace lands on GitHub as **Verified** — which matters because:

- Branch protection rules can require "Verified" commits on protected branches.
- Without verification, `gh pr merge --squash` may still work (GitHub re-signs the squash commit with its web-flow key) but `gh pr merge --auto` can stall waiting on a "signature" check that never resolves.
- The only routine workaround for failing local signing is `gh pr merge --admin`, which **bypasses branch protection entirely** and is exactly the wrong escape hatch for unattended automation.

Goal: keep `--admin` reserved for emergencies; rely on `--auto` for hands-free merges.

### Enabling the feature (one-time, per-user)

1. Visit <https://github.com/settings/codespaces>.
2. Under **GPG verification**, click **Enable** (or confirm it's already on).
3. In the same panel, **add the repo to the trusted list** — Codespaces only signs for repos you explicitly trust. The trust list is per-user.
4. Rebuild any running Codespace for the change to take effect (`Cmd-Shift-P` → *Codespaces: Rebuild Container*).

### Verifying it works in this codespace

```bash
git config --get gpg.program          # expect: /.codespaces/bin/gh-gpgsign
git config --get commit.gpgsign       # expect: true
git commit --allow-empty -m "sign probe"   # should succeed; no "No secret key" error
git log -1 --show-signature           # expect: Good signature from "GitHub <noreply@github.com>"
```

If the probe commit fails with `gpg: skipped "GitHub <noreply@github.com>": No secret key`, the helper is invoked but its identity hasn't propagated to the agent shell. This is qte77/polyforge-orchestrator#64.

### Mitigations while the helper is broken (least to most invasive)

| Mitigation | Effect | When to use |
|---|---|---|
| `git -c commit.gpgsign=false commit ...` | One-shot bypass; this commit unsigned | Single-commit fix you'll PR-merge anyway |
| `git config --local commit.gpgsign false` | All commits in this clone unsigned | Agent loop on a PR that won't require signed commits |
| `gh pr merge --admin --squash` | Bypasses branch protection on merge | **Only** when branch is protected by signed-commit rule and signing is broken; not for routine use |
| `gh pr merge --auto --squash` | Waits for required checks; merges automatically when green | Preferred default once signing works *or* when no signed-commits rule exists |
| Re-enable Codespaces GPG verification (above) and rebuild | Restores `--auto`-friendly state | The intended fix — do this first |

### Why `--auto` over `--admin`

- `--admin` exits success even if checks haven't run; you can ship a red CI accidentally.
- `--auto` waits for **all required checks** (CodeFactor, branch protection, signed commits if required) and merges only when green. Hands-free, no branch-protection bypass.
- Pattern: `gh pr merge <N> --auto --squash --delete-branch` once a PR is ready. GitHub merges it as soon as CI lands green.

### Recovery sequence if `gh-gpgsign` breaks again

1. Try the probe (`git commit --allow-empty -m probe`).
2. If it fails: confirm <https://github.com/settings/codespaces> still shows GPG verification enabled and the repo in the trusted list.
3. Rebuild the codespace.
4. Re-probe.
5. If still broken, disable local signing for this clone (`git config --local commit.gpgsign false`) and continue working unsigned. File the failure on polyforge#64.

## Cross-references

- qte77/polyforge-orchestrator#36 — PAT scope requirements (docs)
- qte77/polyforge-orchestrator#61 — actionable error when fork PAT scope insufficient
- qte77/polyforge-orchestrator#64 — gh-gpgsign fails in agent shells (related root cause)
- This project: PR #17 — `.devcontainer/devcontainer.json` scaffold mirroring polyforge-orchestrator

## TL;DR

- `GH_TOKEN=$GH_PAT` in `containerEnv` fixes `gh pr merge` and similar.
- `git push` still goes through the Codespaces credential helper. Use `gh auth setup-git` if you want `git push` to use `$GH_PAT` too — at the cost of a second plaintext copy.
- All tokens in a running container are plaintext in `/proc/*/environ`. Encryption-at-rest only applies to the GitHub side and to specific keyring-backed configs you explicitly opt into.
- Required PAT scopes vary by operation; see the table above. `gh pr merge` needs `Pull requests: write`; `git push` needs `Contents: write`.
- For `gh pr merge --auto` to work without `--admin`, GPG signing via `gh-gpgsign` must be functional. Enable Codespaces GPG verification at <https://github.com/settings/codespaces>, add this repo to the trusted list, and rebuild.
