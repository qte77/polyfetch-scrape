# Codespaces auth: env-var precedence and plaintext reality

This project's `.devcontainer/devcontainer.json` maps the Codespaces user secret `GH_PAT` into both `GH_PAT` and `GH_TOKEN` env vars. This page documents *why*, what the precedence is for the tools we use, and where tokens land in plaintext.

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

## Cross-references

- qte77/polyforge-orchestrator#36 — PAT scope requirements (docs)
- qte77/polyforge-orchestrator#61 — actionable error when fork PAT scope insufficient
- qte77/polyforge-orchestrator#64 — gh-gpgsign fails in agent shells (related root cause)
- This project: PR #17 — `.devcontainer/devcontainer.json` scaffold mirroring polyforge-orchestrator

## TL;DR

- `GH_TOKEN=$GH_PAT` in `containerEnv` fixes `gh pr merge` and similar.
- `git push` still goes through the Codespaces credential helper. Use `gh auth setup-git` if you want `git push` to use `$GH_PAT` too — at the cost of a second plaintext copy.
- All tokens in a running container are plaintext in `/proc/*/environ`. Encryption-at-rest only applies to the GitHub side and to specific keyring-backed configs you explicitly opt into.
