### Changed

- Release-bump commits are now created via the GitHub GraphQL `createCommitOnBranch` mutation,
  so GitHub signs them with its web-flow key and `main`'s signed-commits ruleset accepts them
  automatically. This removes the manual `git commit --amend --reset-author` re-sign step from
  every release, and needs no GPG secret and no additional allow-listed action.
