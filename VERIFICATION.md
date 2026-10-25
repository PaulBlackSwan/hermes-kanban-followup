# Local verification

Target Hermes source: commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`; existing Python 3.11 interpreter, no new test dependency required.

## Recorded RED → GREEN slices

1. Reused report regression slice: before copying the existing controller, discovery failed because `followup` did not exist; after reuse, 9 report tests passed.
2. Schema/scope/path guard slice: tests first failed because `FollowupError` was missing; implementation added structured errors and minimum physical-table/type checks. Combined report/guard suite: 13 tests passed.
3. Native registration slice: before the manifest/entrypoint/CLI existed, real PluginManager discovery yielded an empty command set and argparse rejected `kanban-followup`. After registration, the native JSON/text/scope/schema tests passed.
4. Trace strictness: `test_boolean_version_is_not_version_one` reproduced an actual assertion failure (`trace_error` unexpectedly None) on the reused code because Python treats `True == 1`. Requiring an integer version fixed it. This RED log is retained locally in `.local/red-version.log` (excluded from distribution).

Final command (run from this repository, substituting the checkout):

```sh
HERMES_SOURCE=/path/to/hermes-agent /path/to/hermes-agent/.venv/bin/python -m unittest discover -s tests -v
```

5. Parent qualification added an actual RED for four non-object JSON event payloads, which previously raised uncaught AttributeError; the report now returns structured `invalid_event_payload` errors. A second RED reproduced terminal escape sequences from a malformed stored identifier; text output now quotes identifiers.

Final parent rerun: **21 tests, OK, no skips**, approximately 4 seconds. Ruff checks also pass. The full output is retained locally in `.local/parent-final-tests.log` (excluded from distribution). Includes real scoped/unrelated synthetic databases, timezone review, trusted/untrusted/latest/old traces, missing database, malformed schema and payloads, terminal-safe identifiers, leaf/parent symlink policy, SQLite write denial, native discovery and actual CLI callbacks in disposable HOME. Native subprocess Python sockets are denied. A spy wraps the real SQLite connect/validator only in the read-only enforcement test; no mock discovery or synthetic CLI responses.

The one independent integrated review found that extreme timezone dates could overflow UTC normalization. Both UTC bounds were reproduced as failing subtests; the parent converts that overflow to a per-comment validation error, preserving healthy cards. The same correction is carried by the separate core helper. Corrections are parent-verified, not independently re-approved by a second review.

The implementation output is retained in `.local/verification.log`; the parent run and extracted-archive qualification are in `.local/parent-final-tests.log` and `.local/extracted-archive-tests.log`. All are excluded by .gitignore. Representative synthetic text from initial qualification:

```text
Kanban follow-up (read-only): 1 scoped, 1 due
Manual report only; no timer, retry, completion or receipt verification.

example [blocked] missing_followup (event 1)
```

No commit, publication, live plugin enablement, production database read, agent inference, Kanban card, service or restart was performed. Only this new project was intentionally edited.

## Important initial test-launcher incident

An initial RED attempt used `python -m hermes_cli.main` with a disposable HOME. Contrary to the assumption that an already-installed interpreter would simply dispatch CLI, Hermes bootstrap printed `preparing dependencies for this data root` and provisioned an isolated runtime before reporting the missing command. This was **unintended PM activity**, not a provider/inference probe or live activation; it must not be described as a wholly PM-free development run. The temporary HOME was cleaned by the test. No further full-bootstrap launches were made.

The final harness therefore directly uses the real native PluginManager, manifest parser, namespace loader and CLI registry, invoking its real argparse setup/handler callbacks without importing the bootstrap entrypoint. This meets native discovery plus registered CLI invocation, but does **not** claim end-to-end verification of the complete `hermes` launcher/PM startup. All final native tests pass under that explicit boundary.

Lesson: a fresh HOME is not enough to prevent package-manager work from a Hermes launcher. Inspect `hermes_bootstrap.py` first; test the discovery SDK directly when launcher provisioning is outside scope.
