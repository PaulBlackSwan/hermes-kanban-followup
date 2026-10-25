# kanban-followup

A standalone Hermes plugin for **manual, read-only, explicitly scoped** diagnostics of blocked/triage Kanban cards. Version 0.1.0. MIT licensed. Python 3.11+, standard library only.

It registers only `hermes kanban-followup` through the documented `ctx.register_cli_command` API. No tools, prompt injection, hooks, background threads, timer, scheduler, network calls, provider credentials, retries, status changes or completion overrides.

## Installation

Install into the intended Hermes profile, then invoke the command from a new CLI process:

```sh
hermes plugins install PaulBlackSwan/hermes-kanban-followup --enable --yes-deps
hermes plugins list
```

This plugin declares no Python dependencies. Installation does not apply the separate core fixes or restart the Gateway. Review the checkout/tag before enabling third-party code. To remove the plugin, use `hermes plugins remove kanban-followup`; this does not alter Kanban cards or comments.

## Usage

After installing and enabling the plugin:

```sh
hermes kanban-followup --db /path/to/kanban.db --coordinator coordinator --session-id exact-session
hermes kanban-followup --db /path/to/kanban.db --coordinator coordinator --session-id exact-session --json
```

All three scope options are mandatory. Values are preserved exactly (whitespace-only values are rejected). No database/profile inventory or implicit HERMES_HOME lookup occurs. DB file symlinks are refused; symlinked parent directories (including a normal symlinked Hermes home) are supported. This is an accidental-target guard, **not** a hostile-filesystem race-proof sandbox. Supply a trusted, stable local path.

Exit 0 means a report was produced, including when cards are due. Exit 2 means an argument or report error. Report errors always use stderr JSON, even in text mode:

```json
{"ok": false, "read_only": true, "error": {"code": "incompatible_schema", "message": "Missing physical table: tasks"}}
```

Argparse usage errors use its normal text stderr. Other error codes include `invalid_scope`, `unsafe_db_path`, `invalid_event_payload` (valid JSON that is not an object), and `report_failed` (missing, locked, corrupt DB or invalid JSON).

## Meaning and limits

Only `blocked`/`triage` cards created by the coordinator **OR** with an exact `(platform=tui, chat_id=session-id, notifier_profile=coordinator)` subscription are inspected. The creator branch intentionally covers that coordinator's cards across sessions in the selected database. No other database/profile is opened. These parameters filter the report; they are not an authorization boundary or a filesystem sandbox. Run only with the local account's approved database access.

The latest event among `blocked`, `block_loop_detected`, `gave_up`, `status` identifies the incident (id 0 if missing). Native comments are considered newest-first. Only the assignee or supplied coordinator is trusted. A comment must start exactly with `BLOCK_FOLLOWUP_V1 ` followed by JSON:

```text
BLOCK_FOLLOWUP_V1 {"version":1,"event_id":42,"owner":"coordinator","next_action":"Ask maintainer to approve","condition":"Approval recorded","review_at":"2026-10-25T12:00:00+02:00","state":"waiting"}
```

Use the **actual current event id**, not this example's 42. `owner`, `next_action`, `condition` must be nonblank strings; review dates need an explicit timezone. States are `waiting` or `resolved`. Old-event traces and untrusted authors are ignored. An invalid latest trusted current-event trace is reported, never silently replaced by an older valid one. A malformed trace on one card does not suppress other cards.

- `missing_followup`: coordinator must inspect and record a current follow-up.
- `waiting`: future review date; no wakeup is scheduled.
- `review_due`: waiting trace at/past the review date.
- `administrative_close`: resolved trace suggests a **human-authorized** administrative action; nothing is closed.

`due` and `due_count` compare the trace date to the scan instant, including resolved traces. They do not prove approval or completion. Cursor movement is reported separately and **never** treated as a receipt; `receipt_verified_by_this_control` is always false. Reports do not persist acknowledgments. Re-run manually when needed. There is no frontend integration or automatic delivery.

SQLite opens with `mode=ro` and `PRAGMA query_only=ON` inside a read transaction. Missing DBs are never created. No migrations or core/internal Kanban imports. SQLite itself may require/read WAL/SHM files for a live WAL database; this does not promise byte-for-byte filesystem immutability of SQLite sidecars or protection against concurrent writers. Avoid `immutable=1` for live databases because it can miss WAL changes.

## Conditional compatibility

Examined against Hermes commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`. Requires documented `register_cli_command`; there is no promise of compatibility with all Hermes versions. The SQLite schema is not a stable public SDK: every report first checks these physical tables and exact declared column types (additional columns allowed):

| Table | Required columns |
|---|---|
| tasks | id TEXT, status TEXT, created_by TEXT, assignee TEXT |
| task_events | id INTEGER, task_id TEXT, kind TEXT, payload TEXT, created_at INTEGER |
| task_comments | id INTEGER, task_id TEXT, author TEXT, body TEXT |
| kanban_notify_subs | task_id TEXT, platform TEXT, chat_id TEXT, notifier_profile TEXT, last_event_id INTEGER |

Optional task columns `block_kind`, `last_failure_error` enhance the report when present. Missing tables, views, renamed columns or incompatible types fail explicitly with `incompatible_schema`. This is a minimal read contract, not full semantic validation of every stored row. Corrupt/malformed event payloads may fail the report rather than return misleading results.

## Tests — no live installation required

From this repository, using an existing Hermes interpreter:

```sh
HERMES_SOURCE=/path/to/hermes-agent /path/to/hermes-agent/.venv/bin/python -m unittest discover -s tests -v
```

Core-free tests run without HERMES_SOURCE; native tests then explicitly skip. All databases are synthetic. Native tests spawn a subprocess with a fresh HOME and HERMES_HOME, empty credential environment, temporary plugin copy and explicit enable config. They use the **real PluginManager discovery, manifest parser, namespaced import and register(ctx)**, then build/invoke argparse from its actual CLI registry (same setup_fn/handler_fn contract as Hermes). No mock loader or directly imported registration function is used. The test harness reads host internals only to retrieve the real command registry; shipped plugin code does not.

The harness deliberately does not launch `python -m hermes_cli.main`, whose bootstrap can provision dependencies for a fresh home before dispatch. This verifies native discovery plus registered CLI execution, **not** the whole bootstrap/PM launcher. See `VERIFICATION.md` for local evidence and the initial bootstrap incident.

## Distribution

Ship only the runtime files (`__init__.py`, `cli.py`, `followup.py`, `plugin.yaml`), public documentation, license and tests. Exclude `.git`, `__pycache__`, `.local`, SQLite files and runtime reports. The plugin contains no core-patching installer and performs no automatic activation or publication.

The report engine reuses the previously tested `kanban_block_followup.py` logic, with schema/path/scope guards and native CLI registration added. No Kanban completion internals are copied or overridden.
