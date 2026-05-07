# Codespaces auth: env-var precedence and plaintext reality

This project's `.devcontainer/devcontainer.json` maps the Codespaces user secret `GH_PAT` into both `GH_PAT` and `GH_TOKEN` env vars. This page documents *why*, what the precedence is for the tools we use, and where tokens land in plaintext. Every non-trivial claim is sourced to GitHub's first-party docs (`docs.github.com/en/codespaces/...`).

## What GitHub auto-injects (without our config)

Per GitHub's [security model for Codespaces](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces): *"Every time a codespace is created or restarted, it's assigned a new GitHub token with an automatic expiry period."* The token's scope depends on the codespace's repository access — write access yields read+write, read-only access triggers automatic forking — and is **not** the same as a user PAT.

The default Codespaces image also pre-configures git with these system-level settings (per [GPG verification troubleshooting](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-gpg-verification-for-github-codespaces)):

- `credential.helper=/.codespaces/bin/gitcredential_github.sh`
- `gpg.program=/.codespaces/bin/gh-gpgsign`
- `user.name` matching your GitHub profile

These are required for the auto-injected token + GPG verification to work. Overriding them via dotfiles is a documented failure cause.

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
| `git` push/fetch (default Codespaces, no `gh auth setup-git`) | global `credential.helper=/.codespaces/bin/gitcredential_github.sh`. Env vars are **not** read directly. |
| `git` push/fetch (after `gh auth setup-git`) | URL-scoped `credential.https://github.com.helper=!/usr/bin/gh auth git-credential` — delegates to `gh`'s precedence above |
| `git` over HTTPS, no helper | URL-embedded `https://x-access-token:TOKEN@github.com/...` (one-shot) |
| GitHub Actions runner | `${{ secrets.GITHUB_TOKEN }}` injected by runner; lifecycle ≠ Codespaces |

### Why `gh auth setup-git` matters

By default in Codespaces, `git push` to GitHub goes through `/.codespaces/bin/gitcredential_github.sh`, which fetches the auto-injected `GITHUB_TOKEN` from the metadata service — **regardless of what you set `GH_TOKEN` to**. Env-var overrides have no effect on `git push`.

`gh auth setup-git` rewrites git's global config to add **URL-scoped helper overrides** for `github.com` and `gist.github.com`:

```
credential.https://github.com.helper=                              # reset
credential.https://github.com.helper=!/usr/bin/gh auth git-credential
```

The empty first entry **resets any inherited helpers** (including the Codespaces system-level one), and the second entry delegates to `gh auth git-credential`. Since `gh` honours `GH_TOKEN` env > `GITHUB_TOKEN` env > stored config, your `containerEnv` mapping now actually flows through to `git push`.

**Cost**: zero net plaintext exposure if `GH_TOKEN` is set. `gh auth git-credential` reads env first, so `~/.config/gh/hosts.yml` stays empty unless you also ran `gh auth login --with-token` (which we don't recommend without a keyring service).

### Implications

- Setting `GH_TOKEN=$GH_PAT` makes `gh pr merge` use `$GH_PAT` regardless of `hosts.yml` or `GITHUB_TOKEN`.
- Setting `GH_TOKEN` propagates to `git push` **only after** `gh auth setup-git` has been run in this codespace. This is automatic via `postCreateCommand` in our `.devcontainer/devcontainer.json`.
- Without `gh auth setup-git`: bypass the helper one-shot via `git -c credential.helper= push "https://x-access-token:$GH_PAT@github.com/..."`.

## Where tokens are plaintext

Per GitHub's [org/repo Codespaces secrets docs](https://docs.github.com/en/codespaces/managing-codespaces-for-your-organization/managing-development-environment-secrets-for-your-repository-or-organization): *"GitHub uses a libsodium sealed box to encrypt secrets before they reach GitHub and only decrypts them when you use them in a codespace."* So at-rest on GitHub's side and in transit (TLS), secrets are encrypted. Inside the running container, by contrast:

| Surface | Plaintext? | Notes |
|---|---|---|
| `/proc/<pid>/environ` | **yes** | Every env var on every process. `containerEnv` mapping puts `$GH_PAT` here. Visible to any process running as the same UID. |
| `~/.config/gh/hosts.yml` | **yes by default** | `gh auth login --with-token` writes the token plaintext unless a system keyring (`secret-service`, `gnome-keyring`, `kwallet`, macOS Keychain) is available. Default Codespaces images run no such service. (Inferred from `gh` CLI behaviour; not an explicit Codespaces docs claim.) |
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

## What this project actually does (env + `gh auth setup-git`)

Two layers, both automated by the devcontainer:

1. **`containerEnv` mapping** — `GH_TOKEN=${localEnv:GH_PAT}` injected from the Codespaces user secret. Fixes `gh pr merge` and any `gh` op that reads env vars.
2. **`postCreateCommand: gh auth setup-git`** — installs gh as the URL-scoped git credential helper for `github.com`. Fixes `git push` by routing it through gh's token resolution.

Net result: a single source of truth (`$GH_PAT`) flows to both `gh` and `git push` operations on GitHub URLs. No second plaintext copy in `~/.config/gh/hosts.yml` (gh reads env first; hosts.yml stays untouched as long as you don't `gh auth login --with-token`).

If/when the qte77 baseline devcontainer adds a keyring service, the trade-off shifts again toward `gh auth login --with-token` (encrypted at rest, no env-var plaintext exposure). For now, env + setup-git is the local optimum.

## GPG signing in Codespaces (gh-gpgsign)

Codespaces ships an opt-in GPG signing helper at `/.codespaces/bin/gh-gpgsign`. Per GitHub's [GPG verification docs](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces): *"GitHub will automatically sign commits you make in GitHub Codespaces, and the commits will have a verified status on GitHub."* The signing key material itself isn't documented publicly; the helper signs against the Codespaces identity service.

When working, every agent commit lands on GitHub as **Verified** — which matters because:

- Branch protection rules can require "Verified" commits on protected branches.
- Without verification, `gh pr merge --squash` may still work (GitHub re-signs the squash commit with its web-flow key) but `gh pr merge --auto` can stall waiting on a "signature" check that never resolves.
- The only routine workaround for failing local signing is `gh pr merge --admin`, which **bypasses branch protection entirely** and is exactly the wrong escape hatch for unattended automation.

**Goal**: keep `--admin` reserved for emergencies; rely on `--auto` for hands-free merges.

### Enabling the feature (one-time, per-user)

Per [docs](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces): *"Your list of trusted repositories for GitHub Codespaces is shared between the GPG verification and Settings Sync features."* Either select **All repositories** or pick **Selected repositories** and choose specific ones.

Steps:

1. Visit <https://github.com/settings/codespaces>.
2. Under **GPG verification**, click **Enable** (or confirm it's already on).
3. Add this repo to the trusted list (the trust list is per-user, shared with Settings Sync).
4. Rebuild any running Codespace for the change to take effect (`Cmd-Shift-P` → *Codespaces: Rebuild Container*).

### Diagnostic audit (run this first)

This one-liner shows every key that affects Codespaces signing **and where each value comes from**, so you can spot dotfiles overrides at a glance:

```bash
for k in commit.gpgsign gpg.program gpg.format user.signingkey credential.helper user.name user.email; do
  printf '%-22s %s\n' "$k" "$(git config --show-origin --get "$k" 2>/dev/null || echo '<unset>')"
done
```

A **healthy** Codespaces config looks like (this codespace, 2026-04):

```
commit.gpgsign         file:/home/vscode/.gitconfig    true
gpg.program            file:/etc/gitconfig             /.codespaces/bin/gh-gpgsign
gpg.format             file:/home/vscode/.gitconfig    openpgp
user.signingkey        <unset>
credential.helper      file:/etc/gitconfig             /.codespaces/bin/gitcredential_github.sh
user.name              file:/etc/gitconfig             qte77
user.email             file:/etc/gitconfig             ...@users.noreply.github.com
```

What to look for:

- `gpg.program` and `credential.helper` **must** come from `/etc/gitconfig` (system-level, set by Codespaces). If they come from `~/.gitconfig` or `.git/config` instead, your dotfiles are overriding them — that's GitHub's documented cause #2.
- `user.signingkey` should be `<unset>` — `gh-gpgsign` signs via the Codespaces identity, not a local GPG key. If it's set, you've configured a local key that gh-gpgsign won't use; harmless but misleading.
- `commit.gpgsign` can come from any scope; only its value matters.

### Verifying signing actually works

```bash
git commit --allow-empty -m "sign probe"   # should succeed; no "No secret key" error
git log -1 --show-signature                # expect: Good signature from "GitHub <noreply@github.com>"
```

### What GitHub officially documents as causes when signing fails

Per [GPG troubleshooting](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-gpg-verification-for-github-codespaces), the documented error message is **`"gpg failed to sign the data"`** with three documented causes:

1. **GPG verification recently disabled.** Git may still attempt signing because `commit.gpgsign=true` is set. Fix: `git config --unset commit.gpgsign`.
2. **Conflicting Git configuration from dotfiles.** Codespaces requires the three system-level settings above (`gpg.program`, `credential.helper`, `user.name`); dotfiles can clobber them. Fix: `git config --global --unset` the conflicting keys, or guard your dotfiles with `[ -n "$CODESPACES" ]`.
3. **VS Code "Enables commit signing with GPG or X.509" setting.** If GPG verification isn't enabled for the repo, deselect this in VS Code preferences.

**Note**: GitHub's troubleshooting docs do **not** cover the `gpg: skipped "GitHub <noreply@github.com>": No secret key` failure mode observed at qte77/polyforge-orchestrator#64. The reproduction conditions for that symptom may be specific to a particular shell / codespace state — see below.

### Status in this codespace (probe results)

Probed 2026-05-07: `git commit --allow-empty -m "sign probe"` succeeded. `git log -1 --show-signature` showed the commit signed with RSA key `B5690EEEBB952194` (GitHub's identity-service signing key for this codespace). The local message `gpg: Can't check signature: No public key` is benign — your local gpg keyring doesn't have GitHub's public key, but GitHub will verify the signature server-side when you push.

This is **inconsistent** with polyforge#64's reported `No secret key` failure. Possible explanations:

- The underlying Codespaces regression has been fixed by GitHub since #64 was filed.
- The failure is intermittent or shell-context dependent (e.g. happens in some agent/SSH shells but not the one running this probe).
- Specific config drift in the codespace where #64 was observed.

If you reproduce the `No secret key` symptom, run the diagnostic audit above and capture the full output before applying any fix — that's the data #64 is missing.

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

### Recovery sequence if `gh-gpgsign` breaks

1. Try the probe (`git commit --allow-empty -m probe`).
2. If it fails with one of the three documented causes (above), apply the documented fix.
3. If it fails with the **undocumented** `No secret key` symptom (qte77/polyforge-orchestrator#64):
   - Confirm <https://github.com/settings/codespaces> still shows GPG verification enabled and the repo in the trusted list.
   - Rebuild the codespace.
   - Re-probe.
4. If still broken: disable local signing for this clone (`git config --local commit.gpgsign false`) and continue working unsigned. Update polyforge#64.

## Cross-references

### GitHub first-party docs

- [Security in Codespaces](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces) — auto-injected token lifecycle and scope rules
- [Managing GPG verification for Codespaces](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces) — enabling and trusted-repo list
- [Troubleshooting GPG verification](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-gpg-verification-for-github-codespaces) — three documented failure causes
- [Org/repo Codespaces secrets](https://docs.github.com/en/codespaces/managing-codespaces-for-your-organization/managing-development-environment-secrets-for-your-repository-or-organization) — libsodium sealed-box encryption
- [REST API: Codespaces secrets](https://docs.github.com/en/rest/codespaces/secrets) — public-key encryption flow

### qte77 cross-repo

- qte77/polyforge-orchestrator#36 — PAT scope requirements (docs)
- qte77/polyforge-orchestrator#61 — actionable error when fork PAT scope insufficient
- qte77/polyforge-orchestrator#64 — `gh-gpgsign` "No secret key" in agent shells (undocumented by GitHub)
- This project: PR #17 — `.devcontainer/devcontainer.json` scaffold mirroring polyforge-orchestrator

## TL;DR

- `GH_TOKEN=$GH_PAT` in `containerEnv` fixes `gh pr merge` and any other `gh` op.
- `gh auth setup-git` (run once via `postCreateCommand`) makes `git push` use `$GH_PAT` too — by delegating git's URL-scoped credential helper to `gh`. **No** second plaintext copy of the token (gh reads env first).
- All tokens in a running container are plaintext in `/proc/*/environ`. Encryption-at-rest applies on GitHub's side and to keyring-backed configs you explicitly opt into.
- Required PAT scopes vary by operation; see the table above. `gh pr merge` needs `Pull requests: write`; `git push` needs `Contents: write`.
- For `gh pr merge --auto` to work without `--admin`, GPG signing via `gh-gpgsign` must be functional. Enable Codespaces GPG verification at <https://github.com/settings/codespaces>, add this repo to the trusted list, and rebuild.
