"""Offline managed-resource identity tests through the real Azure CLI."""

import copy
import io
import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension


class ManagedResourceIdentityCliTests(unittest.TestCase):
    SYSTEM_PRINCIPAL = "11111111-1111-1111-1111-111111111111"
    UAMI_PRINCIPAL = "22222222-2222-2222-2222-222222222222"
    OTHER_PRINCIPAL = "33333333-3333-3333-3333-333333333333"
    SUBSCRIPTION = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    OTHER_SUBSCRIPTION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    UAMI_ID = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/identity-rg"
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
    )
    OTHER_UAMI_ID = UAMI_ID.rsplit("/", 1)[0] + "/other"
    SCOPE = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/monitored-rg"

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        config_dir = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "no",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        }))
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        self.http = stack.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Managed-resource CLI tests must not use the network."),
        ))
        stack.enter_context(patch("azext_sre.custom._cli_invoke", self._nested_command))
        self.agent = {
            "identity": {
                "type": "SystemAssigned, UserAssigned",
                "principalId": self.SYSTEM_PRINCIPAL,
                "userAssignedIdentities": {
                    self.OTHER_UAMI_ID: {"principalId": self.OTHER_PRINCIPAL},
                    self.UAMI_ID: {
                        "principalId": self.UAMI_PRINCIPAL,
                        "clientId": "44444444-4444-4444-4444-444444444444",
                    },
                },
            },
            "properties": {
                "knowledgeGraphConfiguration": {"identity": self.UAMI_ID},
                "actionConfiguration": {"identity": "system", "mode": "Review"},
            },
        }
        self.runtime_configuration = copy.deepcopy(self.agent["properties"])
        self.assignments = []
        self.next_assignment_id = 0

    def tearDown(self):
        self.assertFalse(self.http.called, "A supposedly offline test attempted a network request.")
        self.assertEqual(self.agent["properties"], self.runtime_configuration)

    def _add_assignment(self, principal, role, scope):
        self.next_assignment_id += 1
        assignment = {
            "id": f"assignment-{self.next_assignment_id}",
            "principalId": principal,
            "principalType": "ServicePrincipal",
            "roleDefinitionName": role,
            "scope": scope,
        }
        self.assignments.append(assignment)
        return copy.deepcopy(assignment)

    def _nested_command(self, cli_ctx, *args, **kwargs):
        del cli_ctx, kwargs
        if args[:3] == ("sre", "identity", "show"):
            return copy.deepcopy(self.agent["identity"])
        if args[:2] == ("account", "show"):
            subscription = args[args.index("--subscription") + 1]
            self.assertIn(subscription, ("target-sub", self.SUBSCRIPTION))
            return {"id": self.SUBSCRIPTION}
        self.assertEqual(args[:2], ("role", "assignment"), f"Unexpected command: {args}")
        options = dict(zip(args[3::2], args[4::2]))
        principal = options["--assignee"]
        action = args[2]
        if action == "list":
            subscription_scope = f"/subscriptions/{self.SUBSCRIPTION}"
            return copy.deepcopy([
                assignment for assignment in self.assignments
                if assignment["principalId"] == principal
                and (assignment["scope"] == subscription_scope
                     or "--all" in args and assignment["scope"].startswith(subscription_scope + "/"))
            ])
        role, scope = options["--role"], options["--scope"]
        if action == "create":
            return self._add_assignment(principal, role, scope)
        self.assertEqual(action, "delete")
        self.assignments[:] = [
            assignment for assignment in self.assignments
            if (assignment["principalId"], assignment["roleDefinitionName"], assignment["scope"])
            != (principal, role, scope)
        ]
        return None

    def _invoke(self, action, *arguments, succeeds=True):
        cli = get_default_cli()
        output, errors = io.StringIO(), io.StringIO()
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.WARNING)
        with redirect_stdout(output), redirect_stderr(errors), \
                patch.object(logging.getLogger("cli"), "handlers", [capture]):
            try:
                code = cli.invoke([
                    "sre", "managed-resource", action,
                    "--agent-name", "testagent", "--resource-group", "agent-rg",
                    *arguments,
                ], out_file=output)
            except SystemExit as ex:
                code = ex.code
        if succeeds:
            self.assertEqual(code, 0, errors.getvalue())
        else:
            self.assertNotEqual(code, 0, "An invalid identity/scope was accepted.")
        return output.getvalue(), errors.getvalue()

    def _scope_arguments(self, action):
        return [] if action == "list" else ["--scope", self.SCOPE]

    def test_default_sami_grant_list_revoke_ignores_runtime_uami(self):
        output, _ = self._invoke("grant", "--scope", self.SCOPE)
        granted = json.loads(output)
        self.assertEqual(
            {(item["principalId"], item["roleDefinitionName"], item["scope"]) for item in granted},
            {
                (self.SYSTEM_PRINCIPAL, "Reader", self.SCOPE),
                (self.SYSTEM_PRINCIPAL, "Monitoring Contributor", self.SCOPE),
            },
        )
        self.assertCountEqual(self.assignments, granted)
        for arguments in ([], ["--identity", "system"]):
            with self.subTest(arguments=arguments):
                output, _ = self._invoke("list", *arguments)
                self.assertCountEqual(json.loads(output), granted)
        output, _ = self._invoke("revoke", "--scope", self.SCOPE)
        self.assertEqual(output.strip(), "")
        self.assertEqual(self.assignments, [])

    def test_uami_grant_list_revoke_preserves_unrelated_assignments(self):
        for principal, role, scope in (
            (self.SYSTEM_PRINCIPAL, "Reader", self.SCOPE),
            (self.OTHER_PRINCIPAL, "Monitoring Contributor", self.SCOPE),
            (self.UAMI_PRINCIPAL, "Owner", self.SCOPE),
            (self.UAMI_PRINCIPAL, "Reader", f"/subscriptions/{self.SUBSCRIPTION}"),
            (self.UAMI_PRINCIPAL, "Monitoring Contributor", self.SCOPE + "/providers/Microsoft.Storage/storageAccounts/store"),
            (self.UAMI_PRINCIPAL, "Reader", f"/subscriptions/{self.OTHER_SUBSCRIPTION}"),
            (self.UAMI_PRINCIPAL, "Reader", "/providers/Microsoft.Management/managementGroups/other-mg"),
        ):
            self._add_assignment(principal, role, scope)
        preserved = copy.deepcopy(self.assignments)

        output, _ = self._invoke("grant", "--identity", self.UAMI_ID, "--scope", self.SCOPE)
        granted = json.loads(output)
        self.assertEqual(
            {(item["principalId"], item["roleDefinitionName"], item["scope"]) for item in granted},
            {
                (self.UAMI_PRINCIPAL, "Reader", self.SCOPE),
                (self.UAMI_PRINCIPAL, "Monitoring Contributor", self.SCOPE),
            },
        )
        output, _ = self._invoke("list", "--identity", self.UAMI_ID)
        self.assertCountEqual(json.loads(output), [preserved[2], preserved[3], preserved[4], *granted])
        self._invoke("revoke", "--identity", self.UAMI_ID, "--scope", self.SCOPE)
        self.assertEqual(self.assignments, preserved)

    def test_another_attached_uami_can_be_selected_instead_of_runtime_identity(self):
        output, _ = self._invoke("grant", "--identity", self.OTHER_UAMI_ID, "--scope", self.SCOPE)
        granted = json.loads(output)
        self.assertEqual({item["principalId"] for item in granted}, {self.OTHER_PRINCIPAL})
        self.assertCountEqual(self.assignments, granted)
        output, _ = self._invoke("list", "--identity", self.OTHER_UAMI_ID)
        self.assertCountEqual(json.loads(output), granted)
        self._invoke("revoke", "--identity", self.OTHER_UAMI_ID, "--scope", self.SCOPE)
        self.assertEqual(self.assignments, [])

    def test_uami_only_agent_requires_explicit_selection(self):
        self.agent["identity"].pop("principalId")
        self.agent["identity"]["type"] = "UserAssigned"
        self._invoke("grant", "--identity", self.UAMI_ID, "--scope", self.SCOPE)
        output, _ = self._invoke("list", "--identity", self.UAMI_ID)
        granted = json.loads(output)
        self.assertEqual({item["principalId"] for item in granted}, {self.UAMI_PRINCIPAL})
        self.assertEqual(len(granted), 2)
        for action in ("grant", "list", "revoke"):
            with self.subTest(action=action):
                _, errors = self._invoke(action, *self._scope_arguments(action), succeeds=False)
                self.assertIn("system-assigned", errors)
                self.assertEqual(self.assignments, granted)
        self._invoke("revoke", "--identity", self.UAMI_ID, "--scope", self.SCOPE)
        self.assertEqual(self.assignments, [])

    def test_identity_selection_is_visible_even_when_list_is_empty(self):
        for arguments, principal, description in (
            ([], self.SYSTEM_PRINCIPAL, "system-assigned"),
            (["--identity", "SYSTEM"], self.SYSTEM_PRINCIPAL, "system-assigned"),
            (["--identity", self.UAMI_ID.upper()], self.UAMI_PRINCIPAL, self.UAMI_ID),
        ):
            with self.subTest(arguments=arguments):
                output, errors = self._invoke("list", *arguments)
                self.assertEqual(json.loads(output), [])
                self.assertIn(principal, errors)
                self.assertIn(description, errors)

    def test_invalid_identity_choices_are_rejected_before_any_role_change(self):
        self._add_assignment(self.SYSTEM_PRINCIPAL, "Reader", self.SCOPE)
        preserved = copy.deepcopy(self.assignments)
        for selector in (
            "", " ", "runtime", "system-assigned", self.UAMI_PRINCIPAL,
            self.SCOPE, self.UAMI_ID + "/child", self.UAMI_ID + "?query=invalid",
        ):
            for action in ("grant", "list", "revoke"):
                with self.subTest(selector=selector, action=action):
                    _, errors = self._invoke(
                        action, "--identity", selector, *self._scope_arguments(action), succeeds=False,
                    )
                    self.assertIn("--identity", errors)
                    self.assertEqual(self.assignments, preserved)

    def test_unassigned_uami_is_rejected_for_all_commands(self):
        self._add_assignment(self.SYSTEM_PRINCIPAL, "Reader", self.SCOPE)
        preserved = copy.deepcopy(self.assignments)
        for action in ("grant", "list", "revoke"):
            with self.subTest(action=action):
                _, errors = self._invoke(
                    action, "--identity", self.UAMI_ID + "-unassigned",
                    *self._scope_arguments(action), succeeds=False,
                )
                self.assertIn("not assigned", errors)
                self.assertEqual(self.assignments, preserved)

    def test_missing_uami_principal_metadata_never_falls_back_to_sami(self):
        self._add_assignment(self.SYSTEM_PRINCIPAL, "Reader", self.SCOPE)
        preserved = copy.deepcopy(self.assignments)
        for metadata in (None, {}, {"clientId": "client-only"}, {"principalId": ""}, {"principalId": 123}):
            self.agent["identity"]["userAssignedIdentities"][self.UAMI_ID] = metadata
            for action in ("grant", "list", "revoke"):
                with self.subTest(metadata=metadata, action=action):
                    _, errors = self._invoke(
                        action, "--identity", self.UAMI_ID, *self._scope_arguments(action), succeeds=False,
                    )
                    self.assertIn("principal ID", errors)
                    self.assertEqual(self.assignments, preserved)

    def test_missing_identity_argument_value_is_rejected_by_cli_parser(self):
        for action in ("grant", "list", "revoke"):
            with self.subTest(action=action):
                _, errors = self._invoke(
                    action, *self._scope_arguments(action), "--identity", succeeds=False,
                )
                self.assertIn("--identity", errors)
                self.assertEqual(self.assignments, [])

    def test_malformed_attached_identity_metadata_is_rejected(self):
        self._add_assignment(self.SYSTEM_PRINCIPAL, "Reader", self.SCOPE)
        preserved = copy.deepcopy(self.assignments)
        for identity in (None, [], {"userAssignedIdentities": None}, {"userAssignedIdentities": []}):
            self.agent["identity"] = identity
            for action in ("grant", "list", "revoke"):
                with self.subTest(identity=identity, action=action):
                    _, errors = self._invoke(
                        action, "--identity", self.UAMI_ID, *self._scope_arguments(action), succeeds=False,
                    )
                    self.assertIn("Could not read", errors)
                    self.assertEqual(self.assignments, preserved)

    def test_existing_scope_forms_work_with_selected_uami(self):
        for arguments, expected_scope in (
            (["--target-subscription", "target-sub"], f"/subscriptions/{self.SUBSCRIPTION}"),
            (["--target-subscription", "target-sub", "--target-rg", "monitored-rg"], self.SCOPE),
            (["--management-group", "my-mg"], "/providers/Microsoft.Management/managementGroups/my-mg"),
            (["--scope", self.SCOPE + "/providers/Microsoft.Storage/storageAccounts/store"],
             self.SCOPE + "/providers/Microsoft.Storage/storageAccounts/store"),
        ):
            with self.subTest(arguments=arguments):
                self._invoke("grant", "--identity", self.UAMI_ID, *arguments)
                self.assertEqual(
                    {(item["principalId"], item["roleDefinitionName"], item["scope"]) for item in self.assignments},
                    {
                        (self.UAMI_PRINCIPAL, "Reader", expected_scope),
                        (self.UAMI_PRINCIPAL, "Monitoring Contributor", expected_scope),
                    },
                )
                self._invoke("revoke", "--identity", self.UAMI_ID, *arguments)
                self.assertEqual(self.assignments, [])

    def test_invalid_scope_combinations_do_not_change_roles(self):
        self._add_assignment(self.UAMI_PRINCIPAL, "Reader", self.SCOPE)
        preserved = copy.deepcopy(self.assignments)
        for arguments in (
            [],
            ["--scope", self.SCOPE, "--target-subscription", "target-sub"],
            ["--target-rg", "monitored-rg"],
            ["--management-group", "my-mg", "--target-subscription", "target-sub"],
        ):
            for action in ("grant", "revoke"):
                with self.subTest(arguments=arguments, action=action):
                    self._invoke(action, "--identity", self.UAMI_ID, *arguments, succeeds=False)
                    self.assertEqual(self.assignments, preserved)


if __name__ == "__main__":
    unittest.main()
