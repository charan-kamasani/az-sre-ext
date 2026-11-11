#!/usr/bin/env python3

"""Regenerate the AAZ code of the `az sre` extension from the committed Swagger.

The generated code under ``src/sre/azext_sre/aaz/latest/sre`` is produced by
aaz-dev-tools directly with its final ``sre ...`` command names, so nothing has
to be renamed, overridden or deleted when the extension loads.

Pipeline (all inputs are pinned, so the output is deterministic):

1. Verify the pinned aaz-dev version and that the Azure/aaz checkout contains
   the pinned commit.
2. Add a detached ``git worktree`` of that commit under ``build/aaz-generation``
   (gitignored, removed afterwards), so neither the caller's aaz working tree
   nor stale command models in it can leak into the output.
3. Inside the aaz-dev interpreter, build an in-memory aaz-dev workspace from
   ``specification/app`` (tag ``package-2026-01-01``) and shape the command
   tree with aaz-dev's own workspace API (see ``WORKSPACE_*`` tables below),
   then export the command models to the temporary aaz worktree.
4. Generate the CLI extension code from those command models and copy its
   ``aaz`` package into ``src/sre/azext_sre/aaz`` with LF line endings.
5. Regenerate ``docs/cli-reference.md``.

Usage::

    python scripts/generate_sre_extension.py --aaz-dev <path-to-aaz-dev> --aaz-repo <path-to-Azure/aaz>
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


AAZ_DEV_VERSION = "4.7.1"
AAZ_REPO_COMMIT = "eea0104952d4d28e30c8df1679f7b02801e95046"

EXTENSION_NAME = "sre"
SWAGGER_MODULE = "app"
RESOURCE_PROVIDER = "Microsoft.App"
SWAGGER_TAG = "package-2026-01-01"
API_VERSION = "2026-01-01"
SPEC_MODULE_PATH = Path("specification") / SWAGGER_MODULE
GENERATED_AAZ_PATH = Path("src") / EXTENSION_NAME / f"azext_{EXTENSION_NAME}" / "aaz"

# Resources in the Swagger tag that are intentionally not exposed. The
# `listConnectorsWithSecrets` action is superseded by `az sre connector list-secret`.
EXCLUDED_RESOURCES = (
    "/subscriptions/{}/resourcegroups/{}/providers/microsoft.app/agents/{}/listconnectorswithsecrets",
)

# Command-tree renames applied in order to the workspace aaz-dev builds from
# the Swagger. The first entry of each pair is the name aaz-dev derives from
# the Swagger paths, the second is the final public name.
WORKSPACE_GROUP_RENAMES = (
    (("app",), ("sre",)),
    (("sre", "agent", "connector"), ("sre", "connector")),
    (("sre", "agent", "identity"), ("sre", "identity")),
)
WORKSPACE_COMMAND_RENAMES = (
    (("sre", "supported-agent-model", "list"), ("sre", "agent", "list-models")),
)
# Groups left empty by the renames above.
WORKSPACE_GROUP_DELETES = (
    ("sre", "supported-agent-model"),
)

WORKSPACE_GROUP_HELP = {
    ("sre",): {
        "short": "Manage Azure SRE Agent resources.",
        "lines": ["In PowerShell, pass JSON with --value @file.json instead of inline."],
    },
    ("sre", "agent"): {
        "short": "Manage the core lifecycle of an SRE Agent resource.",
        "lines": ["Create, show, list, update, delete, start, and stop an agent."],
    },
    ("sre", "connector"): {
        "short": "Connect an SRE Agent to an external data source it can query or act on.",
    },
    ("sre", "identity"): {
        "short": "Manage the agent's own managed identity.",
        "lines": [
            "Used for the agent's Azure RBAC-gated calls. Not to be confused with 'sre access' "
            "(who can manage/use the agent) or 'sre repo connect' (repo auth).",
        ],
    },
}

# Argument options, keyed by command and argument variable. The Swagger action
# paths do not give these commands the `-n/--name` aliases the other agent
# commands get.
WORKSPACE_ARG_OPTIONS = {
    (("sre", "agent", "start"), "$Path.agentName"): ["n", "name", "agent-name"],
    (("sre", "agent", "stop"), "$Path.agentName"): ["n", "name", "agent-name"],
}

# Examples for `wait` commands, which aaz-dev synthesizes during CLI generation
# (they have no command model to carry examples).
WAIT_COMMAND_EXAMPLES = {
    ("sre", "agent", "wait"): [
        {
            "name": "Wait until the agent finishes provisioning",
            "commands": ["sre agent wait -g myrg --agent-name myagent --created"],
        },
    ],
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run(command, **kwargs) -> None:
    print("+ " + " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def aaz_dev_python(aaz_dev: str) -> Path:
    """Return the interpreter of the environment aaz-dev is installed in."""
    executable = shutil.which(aaz_dev) or aaz_dev
    bin_dir = Path(executable).resolve().parent
    for name in ("python.exe", "python", "python3"):
        candidate = bin_dir / name
        if candidate.is_file():
            return candidate
    raise SystemExit(f"Cannot find the Python interpreter next to aaz-dev ({executable}).")


def verify_generation_inputs(python: Path, aaz_repo: Path) -> None:
    version = subprocess.check_output(
        [str(python), "-c", "import importlib.metadata as m; print(m.version('aaz-dev'))"],
        text=True,
    ).strip()
    if version != AAZ_DEV_VERSION:
        raise SystemExit(f"Expected aaz-dev {AAZ_DEV_VERSION}, found {version}.")
    result = subprocess.run(
        ["git", "-C", str(aaz_repo), "cat-file", "-e", f"{AAZ_REPO_COMMIT}^{{commit}}"],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Azure/aaz checkout {aaz_repo} does not contain commit {AAZ_REPO_COMMIT}.")


def sync_generated_tree(generated: Path, destination: Path) -> None:
    """Replace destination with generated, writing every file with LF endings."""
    if destination.exists():
        shutil.rmtree(destination)
    for source in sorted(generated.rglob("*")):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        target = destination / source.relative_to(generated)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8").replace("\r\n", "\n")
        target.write_text(text, encoding="utf-8", newline="\n")


def regenerate_cli_reference(root: Path) -> None:
    try:
        import azure.cli.core  # noqa: F401  pylint: disable=unused-import,import-outside-toplevel
    except ImportError:
        print(
            "azure-cli-core is not installed in this interpreter; skipped docs/cli-reference.md. "
            "Run scripts/generate_cli_reference.py with an Azure CLI environment.",
            file=sys.stderr,
        )
        return
    run([sys.executable, root / "scripts" / "generate_cli_reference.py"], cwd=root)


def generate(aaz_dev: str, aaz_repo: Path, root: Path) -> None:
    python = aaz_dev_python(aaz_dev)
    verify_generation_inputs(python, aaz_repo)
    # Scratch space lives under the (gitignored) build/ directory of this repo.
    work_root = root / "build" / "aaz-generation"
    if work_root.exists():
        subprocess.run(["git", "-C", str(aaz_repo), "worktree", "prune"], check=False)
        shutil.rmtree(work_root)
    try:
        aaz_worktree = work_root / "aaz"
        cli_output = work_root / "cli"
        cli_output.mkdir(parents=True)
        run(["git", "-C", aaz_repo, "worktree", "add", "--detach", "--quiet", aaz_worktree, AAZ_REPO_COMMIT])
        try:
            env = dict(os.environ, PYTHONHASHSEED="0", PYTHONUTF8="1")
            run(
                [
                    python,
                    Path(__file__).resolve(),
                    "--in-aaz-dev",
                    json.dumps(
                        {
                            "aaz_path": str(aaz_worktree),
                            "swagger_module_path": str(root / SPEC_MODULE_PATH),
                            "cli_extension_path": str(cli_output),
                        }
                    ),
                ],
                env=env,
            )
        finally:
            run(["git", "-C", aaz_repo, "worktree", "remove", "--force", aaz_worktree])
        sync_generated_tree(
            cli_output / "src" / EXTENSION_NAME / f"azext_{EXTENSION_NAME}" / "aaz",
            root / GENERATED_AAZ_PATH,
        )
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    regenerate_cli_reference(root)


# ---------------------------------------------------------------------------
# The functions below run inside the aaz-dev interpreter (--in-aaz-dev).
# ---------------------------------------------------------------------------


def _configure_aaz_dev(paths: dict) -> None:
    # Importing aaz_dev puts the aaz-dev sources on sys.path.
    import aaz_dev  # noqa: F401  pylint: disable=unused-import,import-outside-toplevel
    from utils.config import Config  # pylint: disable=import-error,import-outside-toplevel

    Config.AAZ_PATH = paths["aaz_path"]
    Config.SWAGGER_PATH = None
    Config.SWAGGER_MODULE_PATH = paths["swagger_module_path"]
    Config.DEFAULT_SWAGGER_MODULE = SWAGGER_MODULE
    Config.DEFAULT_RESOURCE_PROVIDER = RESOURCE_PROVIDER
    Config.CLI_EXTENSION_PATH = paths["cli_extension_path"]


def _tag_resource_map():
    # pylint: disable=import-error,import-outside-toplevel
    from swagger.controller.specs_manager import SwaggerSpecsManager
    from utils.config import Config

    swagger_specs = SwaggerSpecsManager()
    module_manager = swagger_specs.get_module_manager(Config.DEFAULT_PLANE, SWAGGER_MODULE)
    rp = module_manager.get_openapi_resource_provider(RESOURCE_PROVIDER)
    resource_map = rp.get_resource_map_by_tag(SWAGGER_TAG)
    if not resource_map:
        raise SystemExit(f"Swagger tag {SWAGGER_TAG} has no resources.")
    selected = {}
    for resource_id, version_map in resource_map.items():
        if resource_id in EXCLUDED_RESOURCES:
            continue
        versions = list(version_map)
        if versions != [API_VERSION]:
            raise SystemExit(f"Unexpected API versions for {resource_id}: {versions}")
        selected[resource_id] = API_VERSION
    missing = set(EXCLUDED_RESOURCES) - set(resource_map)
    if missing:
        raise SystemExit(f"Excluded resources not found in the Swagger: {sorted(missing)}")
    return swagger_specs, selected


def _generate_command_models() -> dict:
    """Mirror `aaz-dev command-model generate-from-swagger`, shaping the command tree before export."""
    # pylint: disable=import-error,import-outside-toplevel
    from command.controller.specs_manager import AAZSpecsManager
    from command.controller.workspace_manager import WorkspaceManager
    from command.model.configuration import CMDHelp
    from swagger.utils.source import SourceTypeEnum
    from utils.config import Config

    swagger_specs, resources = _tag_resource_map()
    ws = WorkspaceManager.new(
        name=EXTENSION_NAME,
        plane=Config.DEFAULT_PLANE,
        folder=WorkspaceManager.IN_MEMORY,
        mod_names=SWAGGER_MODULE,
        resource_provider=RESOURCE_PROVIDER,
        swagger_manager=swagger_specs,
        aaz_manager=AAZSpecsManager(),
        source=SourceTypeEnum.OpenAPI,
    )
    ws.add_new_resources_by_swagger(
        mod_names=SWAGGER_MODULE,
        version=API_VERSION,
        resources=[{"id": resource_id} for resource_id in resources],
    )

    for names, new_names in WORKSPACE_GROUP_RENAMES:
        ws.rename_command_tree_node(*names, new_node_names=list(new_names))
    for names, new_names in WORKSPACE_COMMAND_RENAMES:
        ws.rename_command_tree_leaf(*names, new_leaf_names=list(new_names))
    for names in WORKSPACE_GROUP_DELETES:
        if not ws.delete_command_tree_node(*names):
            raise SystemExit(f"Command group not found: {' '.join(names)}")
    for names, help_data in WORKSPACE_GROUP_HELP.items():
        ws.update_command_tree_node_help(*names, help=help_data)
    for (names, arg_var), options in WORKSPACE_ARG_OPTIONS.items():
        leaf = ws.find_command_tree_leaf(*names)
        if leaf is None:
            raise SystemExit(f"Command not found: {' '.join(names)}")
        cfg_editor = ws.load_cfg_editor_by_command(leaf)
        arg, _ = cfg_editor.find_arg_by_var(*names, arg_var=arg_var)
        if arg is None:
            raise SystemExit(f"Argument {arg_var} not found in {' '.join(names)}")
        cfg_editor.update_arg_by_var(*names, arg_var=arg_var, options=options)

    unexpected = [
        node.names for node in ws.iter_command_tree_nodes()
        if node is not ws.ws.command_tree and node.names[0] != "sre"
    ]
    if unexpected:
        raise SystemExit(f"Command groups outside 'sre': {unexpected}")

    # Same defaults as generate-from-swagger: short summaries and Swagger
    # examples, generated after renaming so examples use the final names.
    for node in ws.iter_command_tree_nodes():
        if not node.help:
            node.help = CMDHelp()
        if not node.help.short:
            node.help.short = f"Manage {node.names[-1]}"
    for leaf in ws.iter_command_tree_leaves():
        if not leaf.help:
            leaf.help = CMDHelp()
        if not leaf.help.short:
            name = leaf.names[-1]
            leaf.help.short = f"{name[0].upper() + name[1:]} {leaf.names[-2]}"
        command = ws.load_cfg_editor_by_command(leaf).find_command(*leaf.names)
        leaf.examples = ws.generate_examples_by_swagger(leaf, command)

    ws.generate_to_aaz()
    return resources


def _generate_cli_code(resources: dict) -> None:
    """Mirror `aaz-dev cli generate-by-swagger-tag` for the selected resources."""
    # pylint: disable=import-error,import-outside-toplevel,protected-access
    from cli.api._cmds import _build_profile
    from cli.controller.az_atomic_profile_builder import AzAtomicProfileBuilder
    from cli.controller.az_module_manager import AzExtensionManager
    from cli.model.atomic import CLICommandExample
    from command.controller.specs_manager import AAZSpecsManager
    from utils.config import Config

    complete_wait_info = AzAtomicProfileBuilder._complete_command_wait_info.__func__

    def complete_wait_info_with_examples(cls, command_group):
        wait_command = complete_wait_info(cls, command_group)
        examples = WAIT_COMMAND_EXAMPLES.get(tuple(wait_command.names)) if wait_command else None
        if examples:
            wait_command.help.examples = [CLICommandExample(example) for example in examples]
        return wait_command

    AzAtomicProfileBuilder._complete_command_wait_info = classmethod(complete_wait_info_with_examples)

    aaz_specs = AAZSpecsManager()
    commands_map = {}
    for resource_id, version in resources.items():
        cfg_reader = aaz_specs.load_resource_cfg_reader(Config.DEFAULT_PLANE, resource_id, version)
        if not cfg_reader:
            raise SystemExit(f"Command models missing in aaz for {resource_id} {version}")
        for cmd_names, command in cfg_reader.iter_commands():
            commands_map[tuple(cmd_names)] = command.version

    manager = AzExtensionManager()
    if not manager.has_module(EXTENSION_NAME):
        manager.create_new_mod(EXTENSION_NAME)
    module = manager.load_module(EXTENSION_NAME)
    profile = _build_profile(Config.CLI_DEFAULT_PROFILE, commands_map)
    module.profiles[profile.name] = profile
    manager.update_module(EXTENSION_NAME, module.profiles)


def run_in_aaz_dev(paths: dict) -> None:
    _configure_aaz_dev(paths)
    resources = _generate_command_models()
    _generate_cli_code(resources)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate the AAZ code of the az sre extension.")
    parser.add_argument("--aaz-repo", type=Path, help="Path to a local Azure/aaz checkout.")
    parser.add_argument("--aaz-dev", default="aaz-dev", help="Path to the aaz-dev executable.")
    parser.add_argument("--in-aaz-dev", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.in_aaz_dev and not args.aaz_repo:
        parser.error("--aaz-repo is required")
    return args


def main() -> None:
    args = parse_args()
    if args.in_aaz_dev:
        run_in_aaz_dev(json.loads(args.in_aaz_dev))
        return
    generate(aaz_dev=args.aaz_dev, aaz_repo=args.aaz_repo.resolve(), root=repository_root())


if __name__ == "__main__":
    main()
