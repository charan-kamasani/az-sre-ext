#!/usr/bin/env python3
"""Fail fast when the sre extension cannot be discovered by the CLI.

`azdev linter` builds its command table with
``invoker.commands_loader.load_command_table(None)``. An extension whose
loader cannot cope with ``args=None`` is swallowed with only a warning
(``Unable to load extension 'sre: ...'``) and then registers zero commands,
so the linter silently checks nothing. This reproduces that load path and
fails loudly instead.
"""

from __future__ import annotations

import sys


EXPECTED_COMMANDS = (
    "sre version",
    "sre agent create",
    "sre agent delete",
    "sre agent list",
    "sre agent show",
    "sre agent update",
    "sre access grant",
    "sre connector create",
    "sre connector list-secret",
    "sre identity assign",
    "sre managed-resource grant",
    "sre network update",
    "sre repo connect",
    "sre response-plan create",
    "sre skill create",
)


def main() -> int:
    from azure.cli.core import get_default_cli

    from azext_sre import COMMAND_LOADER_CLS

    cli = get_default_cli()
    loader = COMMAND_LOADER_CLS(cli_ctx=cli)
    command_table = loader.load_command_table(None)

    print(f"sre command loader discovered {len(command_table)} commands")

    missing = [name for name in EXPECTED_COMMANDS if name not in command_table]
    if missing:
        print(f"ERROR: sre command loader did not register expected commands with args=None: {missing}",
              file=sys.stderr)
        print(f"Discovered commands: {sorted(command_table)}", file=sys.stderr)
        return 1

    for name in EXPECTED_COMMANDS:
        print(f"  ok: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
