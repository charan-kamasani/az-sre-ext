# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
#
# Auto-discovery wiring, modeled directly on azext-aigateway's commands.py:
# every AAZCommand/AAZCommandGroup subclass defined in custom.py (and ONLY
# custom.py -- generated recipes under aaz/latest/ are untouched) is
# registered under its own AZ_NAME. There is no hand-maintained per-command
# list to keep in sync when a new override is added to custom.py.
#
# One difference from azext-aigateway: that extension's generated swagger
# RP folder already matches its public command name ("aigateway"), so only
# one leaf command needed a name remap (model-provider). The SRE Agent
# swagger's RP folder is "app" (Microsoft.App/agents) end to end, so every
# generated recipe under aaz/latest/app/... is registered by
# load_aaz_command_table as "app agent ..." -- the whole top-level group
# needs renaming to "sre agent ...", not just the ones this module
# overrides. __init__.py already remaps "sre" -> "app" for aaz package
# discovery; this function renames every resulting "app " key here, then
# layers the custom.py overrides (behavioral, not just renamed) on top so
# they always win.
#
# Unlike azext-aigateway, the SRE Agent RP has a single resource family with
# no legacy/new-RP split, so there is no equivalent of aigateway's
# `_rp.route_command` request-routing wrapper to apply here -- generated
# AAZHttpOperation classes already target the right endpoint via their own
# _aaz_info.
# --------------------------------------------------------------------------------------------

# pylint: disable=too-many-lines
# pylint: disable=too-many-statements


def load_command_table(self, _):  # pylint: disable=unused-argument
    import inspect

    from azure.cli.core.aaz import AAZCommand

    from . import custom

    # Rename every generated "app ..." recipe registered by
    # load_aaz_command_table (called by __init__.py before this function) to
    # "sre ...". This extension's aaz package only contains the SRE Agent
    # RP, so a blanket prefix rename is safe.
    for generated_name in list(self.command_table):
        if generated_name == "app" or generated_name.startswith("app "):
            renamed = "sre" + generated_name[len("app"):]
            self.command_table[renamed] = self.command_table.pop(generated_name)
    for generated_name in list(self.command_group_table):
        if generated_name == "app" or generated_name.startswith("app "):
            renamed = "sre" + generated_name[len("app"):]
            self.command_group_table[renamed] = self.command_group_table.pop(generated_name)

    def _is_custom_recipe(value):
        return (
            inspect.isclass(value)
            and issubclass(value, AAZCommand)
            and value is not AAZCommand
            and getattr(value, "AZ_NAME", None)
            and value.__module__ == custom.__name__
        )

    recipes = [value for value in vars(custom).values() if _is_custom_recipe(value)]
    if not recipes:
        raise RuntimeError("azext_sre.custom registered no AAZ command recipes.")
    for recipe in recipes:
        self.command_table[recipe.AZ_NAME] = recipe(loader=self)

    # Drop raw generated duplicates that custom.py deliberately does NOT
    # override/reuse, so they don't linger in the command surface as
    # confusing near-duplicates of the real, documented nouns. These were
    # flagged directly in manager feedback: 'sre agent connector *'
    # duplicates the top-level 'sre connector' noun, 'sre agent identity *'
    # has been promoted to the top-level 'sre identity' noun instead (see
    # custom.py), and 'sre agent list-connectors-with-secret' is replaced
    # by the top-level 'sre connector list-secret'. Every one of these was
    # confirmed, live, to render with a *blank* '--help' description too
    # (see custom.py's '_SupportedAgentModelGroup' comment for why), so
    # removing them also removes a second, independent source of confusion.
    _retired_command_prefixes = (
        "sre agent connector",
        "sre agent identity",
    )
    _retired_commands = (
        "sre agent list-connectors-with-secret",
    )
    for name in list(self.command_table):
        if name in _retired_commands or any(
            name == prefix or name.startswith(prefix + " ") for prefix in _retired_command_prefixes
        ):
            del self.command_table[name]
    for name in list(self.command_group_table):
        if any(name == prefix or name.startswith(prefix + " ") for prefix in _retired_command_prefixes):
            del self.command_group_table[name]


