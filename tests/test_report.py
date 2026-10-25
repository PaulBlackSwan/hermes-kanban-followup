"""Synthetic-only, stdlib regression coverage adapted from the original controller tests."""
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import followup as control

NOW = datetime(2026, 10, 24, 10, tzinfo=UTC)
SCHEMA = """
CREATE TABLE tasks(id TEXT PRIMARY KEY, status TEXT, created_by TEXT, assignee TEXT,
 block_kind TEXT, last_failure_error TEXT);
CREATE TABLE task_events(id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT, payload TEXT, created_at INTEGER);
CREATE TABLE task_comments(id INTEGER PRIMARY KEY, task_id TEXT, author TEXT, body TEXT);
CREATE TABLE kanban_notify_subs(task_id TEXT, platform TEXT, chat_id TEXT, notifier_profile TEXT, last_event_id INTEGER);
"""

class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'board.db'
        self.conn = sqlite3.connect(self.db)
        self.addCleanup(self.conn.close)
        self.conn.executescript(SCHEMA)
        self.task('scoped')

    def task(self, tid, creator='coordinator', status='blocked'):
        self.conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?)',
                          (tid, status, creator, 'worker', 'capability', None))
        self.conn.execute('INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,?,?,?)',
                          (tid, 'blocked', '{"reason":"Approval pending"}', 1))
        self.conn.commit()

    def trace(self, tid='scoped', author='coordinator', **changes):
        eid = self.conn.execute('SELECT MAX(id) FROM task_events WHERE task_id=?', (tid,)).fetchone()[0]
        data = dict(version=1,event_id=eid,owner='coordinator',next_action='Ask maintainer',
                    condition='Approval received',review_at='2026-10-25T10:00:00Z',state='waiting')
        data.update(changes)
        self.comment(tid, author, control.PREFIX + json.dumps(data))

    def comment(self, tid, author, body):
        self.conn.execute('INSERT INTO task_comments(task_id,author,body) VALUES(?,?,?)',(tid,author,body))
        self.conn.commit()

    def scan(self, **kwargs):
        return control.report(self.db, coordinator='coordinator',session_id='session',now=kwargs.get('now', NOW))

    def test_scoped_readonly_missing_followup(self):
        self.task('private','another')
        self.task('finished',status='done')
        before = self.db.read_bytes()
        result = self.scan()
        self.assertEqual([c['task_id'] for c in result['cards']], ['scoped'])
        self.assertEqual(result['due_count'], 1)
        self.assertFalse(result['automatic_timer_created'])
        self.assertFalse(result['cards'][0]['receipt_verified_by_this_control'])
        self.assertEqual(self.db.read_bytes(), before)

    def test_missing_db_not_created(self):
        missing = self.db.parent / 'absent.db'
        with self.assertRaises((OSError, sqlite3.Error, ValueError)):
            control.report(missing,coordinator='coordinator',session_id='session')
        self.assertFalse(missing.exists())

    def test_waiting_due_and_resolved(self):
        self.trace()
        self.assertEqual(self.scan()['due_count'],0)
        due = self.scan(now=control.instant('2026-10-25T12:00:00+02:00'))
        self.assertEqual(due['cards'][0]['control_kind'],'review_due')
        self.trace(state='resolved',review_at='2026-10-24T09:00:00Z')
        self.assertEqual(self.scan()['cards'][0]['control_kind'],'administrative_close')
        self.assertEqual(self.conn.execute('SELECT status FROM tasks').fetchone()[0],'blocked')

    def test_exact_subscription_adopts_card(self):
        self.task('adopted','another')
        for platform, session, profile in [('slack','session','coordinator'),('tui','other','coordinator'),('tui','session','other')]:
            self.conn.execute('INSERT INTO kanban_notify_subs VALUES(?,?,?,?,?)',('adopted',platform,session,profile,999))
        self.conn.commit()
        self.assertEqual(self.scan()['scoped_count'],1)
        self.conn.execute('INSERT INTO kanban_notify_subs VALUES(?,?,?,?,?)',('adopted','tui','session','coordinator',999))
        self.conn.commit()
        cards = self.scan()['cards']
        self.assertEqual({c['task_id'] for c in cards},{'scoped','adopted'})
        adopted = next(c for c in cards if c['task_id']=='adopted')
        self.assertTrue(adopted['cursor_at_or_after_block'])
        self.assertFalse(adopted['receipt_verified_by_this_control'])

    def test_old_event_and_untrusted_author_ignored(self):
        self.trace(event_id=0)
        self.trace(author='stranger')
        self.assertEqual(self.scan()['cards'][0]['control_kind'],'missing_followup')

    def test_assignee_is_trusted(self):
        self.trace(author='worker')
        self.assertEqual(self.scan()['cards'][0]['control_kind'],'waiting')

    def test_malformed_latest_never_falls_back_to_old_valid(self):
        self.trace()
        self.comment('scoped','coordinator',control.PREFIX + '{bad')
        card = self.scan()['cards'][0]
        self.assertTrue(card['due'])
        self.assertIsNotNone(card['trace_error'])

    def test_bad_trace_preserves_other_cards(self):
        self.task('healthy')
        self.trace(tid='healthy')
        for changes in [dict(review_at=None),dict(review_at=123),dict(review_at=[]),dict(review_at={}),
                        dict(review_at='2026-10-25T10:00:00'),dict(owner=''),dict(next_action=''),
                        dict(condition=''),dict(state='closed'),
                        dict(review_at='0001-01-01T00:00:00+01:00'),
                        dict(review_at='9999-12-31T23:59:59-01:00')]:
            with self.subTest(changes=changes):
                self.trace(**changes)
                cards = {c['task_id']: c for c in self.scan()['cards']}
                self.assertIsNotNone(cards['scoped']['trace_error'])
                self.assertEqual(cards['healthy']['control_kind'],'waiting')

    def test_readonly_connection_enforced(self):
        from unittest.mock import patch
        original_connect = sqlite3.connect
        original_validate = control.validate_schema
        observed = []
        def inspect(conn):
            self.assertEqual(conn.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO tasks(id) VALUES('must-not-write')")
            original_validate(conn)
            observed.append(True)
        with patch.object(control.sqlite3, 'connect', wraps=original_connect) as connect:
            with patch.object(control, 'validate_schema', side_effect=inspect):
                self.scan()
            self.assertTrue(connect.call_args.args[0].endswith('?mode=ro'))
            self.assertTrue(connect.call_args.kwargs['uri'])
        self.assertEqual(observed, [True])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)

    def test_boolean_version_is_not_version_one(self):
        self.trace(version=True)
        self.assertIsNotNone(self.scan()['cards'][0]['trace_error'])

    def test_naive_now_rejected(self):
        with self.assertRaises(ValueError):
            self.scan(now=datetime(2026,10,24))
