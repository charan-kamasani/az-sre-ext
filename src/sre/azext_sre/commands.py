# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
#
# Auto-discovery wiring: every AAZCommand/AAZCommandGroup subclass defined
# in custom.py (and ONLY custom.py -- generated recipes under aaz/latest/
# are untouched) is registered under its own AZ_NAME. There is no
# hand-maintained per-command list to keep in sync when a new override is
# added to custom.py.
#
# The generated recipes under aaz/latest/sre/... are generated directly with
# their final "sre ..." names (see scripts/generate_sre_extension.py) and are
# registered by load_aaz_command_table (called by __init__.py before this
# function). The custom.py overrides are layered on top so they always win.
#
# The SRE Agent RP has a single resource family with no legacy/new-RP
# split, so there is no request-routing wrapper to apply here -- generated
# AAZHttpOperation classes already target the right endpoint via their own
# _aaz_info.
# --------------------------------------------------------------------------------------------

# pylint: disable=too-many-lines
# pylint: disable=too-many-statements


def load_command_table(self, _):  # pylint: disable=unused-argument
    import inspect

    from azure.cli.core.aaz import AAZCommand, AAZCommandGroup

    from . import custom

    def _is_custom_recipe(value):
        return (
            inspect.isclass(value)
            and issubclass(value, AAZCommand)
            and value is not AAZCommand
            and getattr(value, "AZ_NAME", None)
            and value.__module__ == custom.__name__
        )

    from ._transformers import TABLE_TRANSFORMERS

    recipes = [value for value in vars(custom).values() if _is_custom_recipe(value)]
    if not recipes:
        raise RuntimeError("azext_sre.custom registered no AAZ command recipes.")
    for recipe in recipes:
        table_transformer = TABLE_TRANSFORMERS.get(recipe.AZ_NAME)
        kwargs = {"table_transformer": table_transformer} if table_transformer else {}
        self.command_table[recipe.AZ_NAME] = recipe(loader=self, **kwargs)

    # Groups declared in custom.py also need to be in command_group_table so
    # azdev linter matches their help entries to a real group.
    for value in vars(custom).values():
        if (
            inspect.isclass(value)
            and issubclass(value, AAZCommandGroup)
            and value is not AAZCommandGroup
            and getattr(value, "AZ_NAME", None)
            and value.__module__ == custom.__name__
        ):
            self.command_group_table[value.AZ_NAME] = value(cli_ctx=self.cli_ctx)
