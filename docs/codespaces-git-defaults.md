# Codespaces git config: baked defaults and per-repo overrides

Codespaces images bake several git config values into `~/.gitconfig` (the per-user "global" scope) so every repo opened in the container behaves consistently. Repos that don't explicitly override these inherit them automatically.

This doc covers git-config defaults that aren't directly auth-related (those are in [`codespaces-auth.md`](codespaces-auth.md)) and how to override them per-repo when the global value isn't what you want.

## How git config layering works

Git resolves a key by walking four scopes, later scopes overriding earlier:

1. **system** — `/etc/gitconfig` (Codespaces image populates `gpg.program`, `credential.helper`, `user.name`, `user.email` here)
2. **global** — `~/.gitconfig` (Codespaces or your dotfiles populate things here)
3. **local** — `.git/config` (this repo only)
4. **worktree** — `.git/config.worktree` (rare; only when worktree-specific config is enabled)

Quick inspection commands:

```bash
git config --get <key>                # value from highest-priority scope that defines it
git config --show-origin --get <key>  # also prints which file the value came from
git config --list --show-origin       # everything, with origins
```

## `commit.template`

Codespaces commonly sets `commit.template=/home/vscode/.gitmessage` at the global level, providing a default commit-message scaffold for every repo. Repos that ship their own `.gitmessage` at the repo root **don't get it used automatically** — git keeps using the global one until you explicitly opt the local repo in.

### Use the repo's own `.gitmessage`

```bash
git config --local commit.template .gitmessage
```

Writes the entry to `.git/config`. Local scope wins for this repo; global stays unaffected for other repos.

### Disable the template for this repo

```bash
git config --local commit.template ""
```

Setting local to empty string overrides the inherited global value. (Plain `--unset commit.template` only removes the key from local; the global value then resurfaces — which is the opposite of what you want.)

### Verify which template is in effect

```bash
git config --show-origin --get commit.template
```

Expect to see `file:.git/config` if you opted in to the repo-local template, or `file:/home/vscode/.gitconfig` if you're still inheriting the global default.

## Why this matters for this project

If we ever add a `./.gitmessage` to enforce a Conventional-Commits scaffold, every contributor will need the local-scope opt-in — otherwise their first commit uses whatever Codespaces or their dotfiles happen to provide. A `.devcontainer/devcontainer.json` `postCreateCommand` is the natural place to wire that up automatically:

```json
"postCreateCommand": "gh auth setup-git && [ -f .gitmessage ] && git config --local commit.template .gitmessage"
```

Currently we don't ship a `./.gitmessage`, so the global default is fine and no override is needed.

## See also

- [`codespaces-auth.md`](codespaces-auth.md) — auth and credentials side of Codespaces git defaults (`gpg.program`, `credential.helper`, GPG signing flow, PAT scopes)
- [Pro Git → Customizing Git → Git Configuration](https://git-scm.com/book/en/v2/Customizing-Git-Git-Configuration) — full git config layering reference (1p)
