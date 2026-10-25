#!/usr/bin/env python3
"""Read-only blocked-card control; durable follow-up traces are native comments.

No scheduler, network, delivery, state writes, unblock or retry is performed.
Reports are invoked manually; this module never registers wakeups.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

PREFIX = "BLOCK_FOLLOWUP_V1 "
STATES = {"waiting", "resolved"}


def instant(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("review_at must be a non-empty ISO 8601 string")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("review_at must include an explicit timezone")
    try:
        return result.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("review_at is outside the supported UTC range") from exc


def validate_trace(data: dict, event_id: int) -> dict:
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("expected follow-up version 1 object")
    if type(data.get("event_id")) is not int or data["event_id"] != event_id:
        raise ValueError("trace does not match current block event")
    for name in ("owner", "next_action", "condition"):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError(f"missing {name}")
    if data.get("state") not in STATES:
        raise ValueError("state must be waiting or resolved")
    instant(data["review_at"])
    return data


def trace_from_comments(comments: list[dict], event_id: int, trusted: set[str]):
    for comment in reversed(comments):
        if comment["author"] not in trusted or not comment["body"].startswith(PREFIX):
            continue
        try:
            value = json.loads(comment["body"][len(PREFIX):])
            # An old incident's trace must never silence a new block.
            if isinstance(value, dict) and value.get("event_id") != event_id:
                continue
            return validate_trace(value, event_id), None, comment["id"]
        except (ValueError, TypeError, KeyError) as exc:
            return None, f"invalid follow-up comment {comment['id']}: {exc}", comment["id"]
    return None, None, None


def inspect_card(conn, task: dict, coordinator: str, session_id: str, now: datetime) -> dict:
    row = conn.execute(
        "SELECT id, kind, payload, created_at FROM task_events WHERE task_id=? "
        "AND kind IN ('blocked','block_loop_detected','gave_up','status') ORDER BY id DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    event = dict(row) if row else {"id": 0, "kind": "missing", "payload": None, "created_at": 0}
    payload = json.loads(event["payload"]) if event["payload"] else {}
    if not isinstance(payload, dict):
        raise FollowupError('invalid_event_payload', 'Event payload must be a JSON object')
    reason = payload.get("reason") or payload.get("error") or task.get("last_failure_error") or "Reason not recorded"
    comments = [dict(r) for r in conn.execute(
        "SELECT id,author,body FROM task_comments WHERE task_id=? ORDER BY id", (task["id"],)
    )]
    trusted = {coordinator, task.get("assignee") or ""}
    trace, issue, comment_id = trace_from_comments(comments, event["id"], trusted)
    sub = conn.execute(
        "SELECT last_event_id FROM kanban_notify_subs WHERE task_id=? "
        "AND platform='tui' AND chat_id=? AND notifier_profile=?",
        (task["id"], session_id, coordinator),
    ).fetchone()
    if trace:
        due = instant(trace["review_at"]) <= now
        kind = "administrative_close" if trace["state"] == "resolved" else "review_due" if due else "waiting"
        owner, action = trace["owner"], trace["next_action"]
        condition, review_at = trace["condition"], trace["review_at"]
    else:
        due, kind, owner = True, "missing_followup", coordinator
        action = "Inspect kanban_show; record owner, concrete next action and review_at. No automatic retry."
        condition, review_at = "Coordinator records a current follow-up trace", None
    return {
        "task_id": task["id"], "status": task["status"], "event_id": event["id"],
        "block_kind": task.get("block_kind"), "reason": reason, "owner": owner,
        "next_action": action, "condition": condition, "review_at": review_at,
        "state": trace["state"] if trace else "unmanaged", "control_kind": kind,
        "due": due, "trace_comment_id": comment_id, "trace_error": issue,
        "route_present": sub is not None,
        # Cursor movement is NOT a user/agent receipt. Kept deliberately separate.
        "cursor_at_or_after_block": bool(sub and sub["last_event_id"] >= event["id"]),
        "receipt_verified_by_this_control": False,
    }


class FollowupError(ValueError):
    """Actionable compatibility/scope error, suitable for structured CLI output."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# Minimum read contract examined against Hermes bf0203a; extra columns are allowed.
REQUIRED_COLUMNS = {
    'tasks': {'id': 'TEXT', 'status': 'TEXT', 'created_by': 'TEXT', 'assignee': 'TEXT'},
    'task_events': {'id': 'INTEGER', 'task_id': 'TEXT', 'kind': 'TEXT', 'payload': 'TEXT', 'created_at': 'INTEGER'},
    'task_comments': {'id': 'INTEGER', 'task_id': 'TEXT', 'author': 'TEXT', 'body': 'TEXT'},
    'kanban_notify_subs': {'task_id': 'TEXT', 'platform': 'TEXT', 'chat_id': 'TEXT', 'notifier_profile': 'TEXT', 'last_event_id': 'INTEGER'},
}


def validate_schema(conn):
    for table, expected in REQUIRED_COLUMNS.items():
        kind = conn.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
        if not kind or kind[0] != 'table':
            raise FollowupError('incompatible_schema', f'Missing physical table: {table}')
        actual = {row['name']: row['type'].upper() for row in conn.execute(f'PRAGMA table_info("{table}")')}
        if any(actual.get(name) != datatype for name, datatype in expected.items()):
            raise FollowupError('incompatible_schema', f'Unsupported columns or types in {table}; see README schema contract')


def report(db_path: Path, *, coordinator: str, session_id: str, now: datetime | None = None) -> dict:
    if not all(isinstance(value, str) and value.strip() for value in (coordinator, session_id)):
        raise FollowupError('invalid_scope', 'Explicit non-empty coordinator and session_id are required')
    db_path = Path(db_path).expanduser()
    if db_path.is_symlink():
        raise FollowupError('unsafe_db_path', 'Database file symlinks are refused; parent/home symlinks are allowed')
    if db_path.exists() and not db_path.is_file():
        raise FollowupError('unsafe_db_path', 'Database must be a regular file')
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # mode=ro refuses a missing DB and cannot migrate, initialize or create one.
    conn = sqlite3.connect(db_path.expanduser().resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        validate_schema(conn)
        tasks = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE status IN ('blocked','triage') AND "
            "(created_by=? OR EXISTS (SELECT 1 FROM kanban_notify_subs s "
            "WHERE s.task_id=tasks.id AND s.platform='tui' AND s.chat_id=? "
            "AND s.notifier_profile=?)) ORDER BY id",
            (coordinator, session_id, coordinator),
        )]
        cards = [inspect_card(conn, task, coordinator, session_id, now) for task in tasks]
        return {
            "version": 1, "read_only": True, "coordinator": coordinator,
            "session_id": session_id, "checked_at": now.astimezone(UTC).isoformat(),
            "scoped_count": len(cards), "due_count": sum(card["due"] for card in cards),
            "cards": cards, "automatic_timer_created": False,
        }
    finally:
        conn.close()
