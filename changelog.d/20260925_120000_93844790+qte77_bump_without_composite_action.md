### Fixed

- The **Bump version** workflow failed at job setup after `callowayproject/bump-my-version` moved to
  1.5: the action became a composite that nests unpinned `actions/checkout@v7`,
  `actions/setup-python@v7` and `ad-m/github-push-action@master` (the last one force-pushes to the
  branch), which the repository's SHA-pinning Actions policy rejects. The workflow now runs the
  pinned CLI directly (`uvx bump-my-version@1.5.1`), with the same outputs, and no third-party
  action.
