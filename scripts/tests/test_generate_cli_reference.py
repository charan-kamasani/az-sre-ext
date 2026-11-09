import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from scripts.generate_cli_reference import render_reference


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
