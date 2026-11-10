import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from scripts.generate_cli_reference import render_reference


class ReferenceMetadataTests(unittest.TestCase):
    def test_reference_is_identical_for_different_signed_in_tenants(self):
        outputs = []
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            for tenant in ("72f988bf-86f1-41af-91ab-2d7cd011db47",
                           "11111111-2222-3333-4444-555555555555"):
                (config / "azureProfile.json").write_text(json.dumps({
                    "subscriptions": [{"isDefault": True, "tenantId": tenant}],
                }), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-c",
                     "import pathlib,sys; sys.path.insert(0,str(pathlib.Path.cwd())); "
                     "from scripts.generate_cli_reference import render_reference; "
                     "sys.stdout.write(render_reference())"],
                    cwd=Path(__file__).resolve().parents[2],
                    env={**os.environ, "AZURE_CONFIG_DIR": str(config), "PYTHONUTF8": "1"},
                    capture_output=True, text=True, encoding="utf-8", check=True,
                )
                outputs.append(result.stdout)
        self.assertTrue(outputs[0])
        self.assertEqual(outputs[0], outputs[1])


@unittest.skipUnless(shutil.which("bash"), "Bash is required to exercise copied examples.")
class ReferenceExampleTests(unittest.TestCase):
    def _rendered_script(self, text):
        rendered = render_reference({
            "commands": {
                "sre example": {"help": {"examples": [{"name": None, "text": text}]}, "options": []},
            },
            "groups": {"sre": {"help": {}}},
        })
        blocks = re.findall(r"(?ms)^ *```bash\n(.*?)^ *```\s*$", rendered)
        if not blocks:
            blocks = re.findall(r"(?m)^  `(.*)`$", rendered)
        self.assertEqual(len(blocks), 1, "The reference must contain one copyable example.")
        return textwrap.dedent(blocks[0])

    def _run(self, script, directory):
        result = subprocess.run(
            [shutil.which("bash"), "-euo", "pipefail", "-c",
             "az() { printf '%s\\0' \"$@\"; }\n" + script],
            cwd=directory, capture_output=True, check=True,
        )
        return result.stdout.decode().rstrip("\0").split("\0")

    def test_copied_multiline_command_preserves_arguments_and_json_content(self):
        payload = '{"description": "Keep  two spaces | and a `backtick`", "enabled": true}'
        script = self._rendered_script(
            "az sre example --name test \\\n"
            f"    --value '{payload}'"
        )
        with tempfile.TemporaryDirectory() as directory:
            arguments = self._run(script, directory)
        self.assertEqual(arguments, ["sre", "example", "--name", "test", "--value", payload])

    def test_copied_example_creates_its_json_file_before_the_cli_reads_it(self):
        payload = {"prompt": "Keep  these spaces | and punctuation."}
        script = self._rendered_script(
            "cat > instructions.json <<'JSON'\n"
            + json.dumps(payload, indent=2)
            + "\nJSON\n"
            + "az sre instructions create --name example \\\n"
            + "    --value @instructions.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            arguments = self._run(script, directory)
            value_path = Path(directory) / arguments[arguments.index("--value") + 1][1:]
            self.assertEqual(json.loads(value_path.read_text()), payload)
        self.assertEqual(arguments, [
            "sre", "instructions", "create", "--name", "example", "--value", "@instructions.json",
        ])


if __name__ == "__main__":
    unittest.main()
