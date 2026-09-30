### Changed

- `make changelog_new` no longer stages the fragment it creates (`scriv create` without `--add`).
  Staging the empty template at creation let commits capture the template instead of the edited
  entry. Edit the fragment, then `git add` it; CONTRIBUTING documents the step.
