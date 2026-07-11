### Changed

- CI/release: adopted the [scriv](https://scriv.readthedocs.io/) `changelog.d/` fragment workflow — per-PR fragments (`make changelog_new`) are collected into a dated `CHANGELOG.md` section by the **Bump version** workflow (`scriv collect`), replacing manual `## [Unreleased]` editing (and its merge conflicts). `bump-my-version` no longer rewrites `CHANGELOG.md`. Mirrors the qte77 sibling repos.
