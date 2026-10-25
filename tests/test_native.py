"""Real Hermes CLI in an isolated HOME; no provider or production data."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from test_report import SCHEMA

ROOT = Path(__file__).resolve().parents[1]

class NativeTests(unittest.TestCase):
    def setUp(self):
        source = os.environ.get('HERMES_SOURCE')
        if not source:
            self.skipTest('Set HERMES_SOURCE to the Hermes checkout for native integration')
        self.source = Path(source).resolve()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        profile = self.home / '.hermes'
        target = profile / 'plugins' / 'kanban-followup'
        target.mkdir(parents=True)
        for name in ['__init__.py','cli.py','followup.py','plugin.yaml']:
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, target / name)
        (profile / 'config.yaml').write_text('plugins:\n  enabled: [kanban-followup]\n')
        self.env = {'HOME':str(self.home),'HERMES_HOME':str(profile),
                    'PATH':'/usr/bin:/bin','PYTHONPATH':str(self.source),
                    'TMPDIR':os.environ['TMPDIR'],'PYTHONDONTWRITEBYTECODE':'1'}
        self.db = self.home / 'synthetic.db'
        with sqlite3.connect(self.db) as conn:
            conn.executescript(SCHEMA)
            conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?)',('example','blocked','coordinator','worker','capability',None))
            conn.execute('INSERT INTO task_events VALUES(?,?,?,?,?)',(1,'example','blocked','{"reason":"Approval pending"}',1))

    def invoke(self, *args):
        harness = '''import argparse, sys, socket

def deny_network(*args, **kwargs):
    raise RuntimeError("Network is forbidden during native plugin verification")
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
from hermes_cli.plugins import PluginManager
manager = PluginManager()
manager.discover_and_load()
parser = argparse.ArgumentParser(prog="hermes")
subs = parser.add_subparsers(dest="command", required=True)
for entry in manager._cli_commands.values():
    child = subs.add_parser(entry["name"], help=entry["help"])
    entry["setup_fn"](child)
    if entry.get("handler_fn"):
        child.set_defaults(func=entry["handler_fn"])
args = parser.parse_args()
sys.exit(args.func(args) or 0)
'''
        return subprocess.run([sys.executable,'-c',harness,'kanban-followup',*args],
                              cwd=self.home,env=self.env,capture_output=True,text=True,timeout=60)

    def test_native_discovery_json_and_text(self):
        before = self.db.read_bytes()
        args = ['--db',str(self.db),'--coordinator','coordinator','--session-id','session']
        result = self.invoke(*args,'--json')
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['scoped_count'],1)
        self.assertEqual(report['cards'][0]['task_id'],'example')
        text = self.invoke(*args)
        self.assertEqual(text.returncode,0,text.stderr)
        self.assertIn('next action:',text.stdout)
        self.assertIn('missing_followup', text.stdout)
        self.assertEqual(self.db.read_bytes(),before)
        print('NATIVE_JSON=' + json.dumps(report,sort_keys=True))
        print('NATIVE_TEXT=' + text.stdout.strip())

    def test_native_structured_schema_error(self):
        bad = self.home / 'empty.db'
        sqlite3.connect(bad).close()
        result = self.invoke('--db',str(bad),'--coordinator','coordinator','--session-id','session','--json')
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['code'],'incompatible_schema')

    def test_native_missing_database_not_created(self):
        missing = self.home / 'absent.db'
        result = self.invoke('--db',str(missing),'--coordinator','coordinator','--session-id','session','--json')
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertTrue(json.loads(result.stderr)['read_only'])
        self.assertFalse(missing.exists())

    def test_native_nonobject_event_payload_is_structured_error(self):
        for payload in ('[]', 'null', '"not an object"', '1'):
            with self.subTest(payload=payload):
                with sqlite3.connect(self.db) as conn:
                    conn.execute('UPDATE task_events SET payload=? WHERE id=1', (payload,))
                result = self.invoke('--db', str(self.db), '--coordinator', 'coordinator',
                                     '--session-id', 'session', '--json')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(json.loads(result.stderr)['error']['code'], 'invalid_event_payload')

    def test_native_text_does_not_emit_terminal_controls_from_identifiers(self):
        unsafe_id = 'example\x1b[31m'
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE tasks SET id=? WHERE id=?', (unsafe_id, 'example'))
            conn.execute('UPDATE task_events SET task_id=? WHERE task_id=?', (unsafe_id, 'example'))
        result = self.invoke('--db', str(self.db), '--coordinator', 'coordinator',
                             '--session-id', 'session')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('\x1b', result.stdout)
        self.assertIn('\\u001b', result.stdout)

    def test_native_requires_explicit_scope(self):
        result = self.invoke('--db',str(self.db),'--json')
        self.assertEqual(result.returncode,2)
        self.assertIn('--coordinator',result.stderr)
        self.assertIn('--session-id',result.stderr)
