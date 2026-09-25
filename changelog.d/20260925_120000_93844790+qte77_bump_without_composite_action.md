### Fixed

- The **Bump version** workflow failed at job setup after `callowayproject/bump-my-version` moved to
  1.5: the action became a composite that nests unpinned `actions/checkout@v7`,
  `actions/setup-python@v7` and `ad-m/github-push-action@master` (the last one force-pushes to the
  branch), which the repository's SHA-pinning Actions policy rejects. The workflow now runs the
  pinned CLI directly (`uvx bump-my-version@1.5.1`), with the same outputs, and no third-party
  action.
- Its signed-commit step (first exercised end-to-end here) died with `jq: Argument list too long`:
  each changed file's base64 was passed as a command-line argument, and `uv.lock` alone exceeds
  Linux's 128 KiB per-argument limit. The payload is now built through files, and the release
  branch is only created once the payload is ready, so a failure leaves no orphan branch.
