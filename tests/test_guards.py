import sqlite3
import unittest

import test_report
import followup as control


class GuardTests(unittest.TestCase):
    setUp = test_report.ReportTests.setUp
    task = test_report.ReportTests.task
    def test_incompatible_schema_rejected_before_rows(self):
        for ddl in ['DROP TABLE task_comments',
                    'ALTER TABLE task_comments RENAME COLUMN body TO content',
                    'DROP TABLE task_comments; CREATE VIEW task_comments AS SELECT 1 AS id, 2 AS task_id, 3 AS author, 4 AS body']:
            with self.subTest(ddl=ddl):
                other = self.db.parent / 'bad.db'
                if other.exists():
                    other.unlink()
                from test_report import SCHEMA
                with sqlite3.connect(other) as conn:
                    conn.executescript(SCHEMA + ddl)
                with self.assertRaises(control.FollowupError) as caught:
                    control.report(other,coordinator='coordinator',session_id='session')
                self.assertEqual(caught.exception.code,'incompatible_schema')

    def test_empty_scope_rejected(self):
        for coordinator, session in [('', 'session'),('coordinator',''),(' ', 'session')]:
            with self.assertRaises(control.FollowupError) as caught:
                control.report(self.db,coordinator=coordinator,session_id=session)
            self.assertEqual(caught.exception.code,'invalid_scope')

    def test_db_leaf_symlink_refused_parent_symlink_allowed(self):
        link = self.db.parent / 'alias.db'
        link.symlink_to(self.db)
        with self.assertRaises(control.FollowupError) as caught:
            control.report(link,coordinator='coordinator',session_id='session')
        self.assertEqual(caught.exception.code,'unsafe_db_path')
        parent = self.db.parent / 'home-alias'
        parent.symlink_to(self.db.parent, target_is_directory=True)
        self.assertEqual(control.report(parent / 'board.db',coordinator='coordinator',session_id='session')['scoped_count'],1)

    def test_missing_schema_structured(self):
        other = self.db.parent / 'empty.db'
        sqlite3.connect(other).close()
        with self.assertRaises(control.FollowupError) as caught:
            control.report(other,coordinator='coordinator',session_id='session')
        self.assertEqual(caught.exception.code,'incompatible_schema')
