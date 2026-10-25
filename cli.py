"""Native argparse command; registration never opens a database."""
import json
from pathlib import Path
import sqlite3
import sys

from .followup import FollowupError, report


def setup_parser(parser):
    parser.add_argument('--db', type=Path, required=True, help='Explicit SQLite file (no automatic discovery)')
    parser.add_argument('--coordinator', required=True)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON')


def handle(args):
    try:
        result = report(args.db, coordinator=args.coordinator, session_id=args.session_id)
    except (sqlite3.Error, ValueError, TypeError, KeyError, OSError) as exc:
        code = exc.code if isinstance(exc, FollowupError) else 'report_failed'
        print(json.dumps({'ok': False, 'read_only': True,
                          'error': {'code': code, 'message': str(exc)}}), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Kanban follow-up (read-only): {result['scoped_count']} scoped, {result['due_count']} due")
        print('Manual report only; no timer, retry, completion or receipt verification.')
        for card in result['cards']:
            task_id = json.dumps(card['task_id'], ensure_ascii=True)
            print(f"\n{task_id} [{card['status']}] {card['control_kind']} (event {card['event_id']})")
            for label, key in [('reason','reason'),('owner','owner'),('next action','next_action'),
                               ('condition','condition'),('review at','review_at'),('trace error','trace_error')]:
                value = card[key]
                # Quote stored values so terminal control sequences remain inert.
                print(f"  {label}: {json.dumps(value, ensure_ascii=True)}")
    return 0
