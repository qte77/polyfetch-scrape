### Fixed

- `easter-hunt scan`: seed-file reading moved into its own helper, so `_resolve_seeds` stays under the complexipy limit with complexipy 8.3 (it scored 17 against 15 and failed `make complexity` on the Dependabot bump #276). No behaviour change.
