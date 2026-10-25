"""CLI-only, read-only Kanban follow-up plugin."""
from .cli import setup_parser, handle


def register(ctx):
    if not callable(getattr(ctx, 'register_cli_command', None)):
        raise RuntimeError('kanban-followup requires the documented register_cli_command SDK')
    ctx.register_cli_command(name='kanban-followup',help='Read-only scoped blocked-card report',
                             setup_fn=setup_parser,handler_fn=handle)
