import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = {"app.py", "scout.py", "telegram_alerts.py"}
DEPENDENCY_OWNERS = {
    "flask": {"app.py"},
    "sqlite3": {"scout.py"},
    "bs4": {"scout.py"},
    "requests": {"scout.py", "telegram_alerts.py"},
}
APP_IMPORTS = {
    "scout": {"Collector", "Store", "evaluate", "source_catalog", "validate_settings"},
    "telegram_alerts": {"is_configured", "notify"},
}


def production_paths(root):
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    )
    return {
        path for path in output.decode().split("\0")
        if path.endswith(".py") and Path(path).parts[0] not in {"tests", "scripts"}
    }


def import_errors(path, source):
    errors = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if isinstance(node, ast.Import):
            imports = [(alias.name, None) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                errors.append(f"{path}:{node.lineno}: relative import needs an explicit ownership decision.")
                continue
            imports = [(node.module or "", alias.name) for alias in node.names]
        else:
            continue
        for module, name in imports:
            dependency = module.split(".")[0]
            location = f"{path}:{node.lineno}"
            if dependency + ".py" in MODULES:
                allowed = APP_IMPORTS.get(module, set()) if path == "app.py" else set()
                if name not in allowed:
                    errors.append(f"{location}: import {module}.{name or '*'} crosses module ownership. "
                                  "Use app's named public imports; keep scout and Telegram independent.")
            elif dependency in DEPENDENCY_OWNERS:
                owners = DEPENDENCY_OWNERS[dependency]
                if path not in owners:
                    errors.append(f"{location}: {dependency} belongs in {', '.join(sorted(owners))}.")
            elif dependency not in sys.stdlib_module_names and dependency != "__future__":
                errors.append(f"{location}: declare an owner in DEPENDENCY_OWNERS before importing {dependency}.")
    return errors


class ArchitectureTests(unittest.TestCase):
    def test_every_production_module_has_deliberate_ownership(self):
        unknown = production_paths(ROOT) - MODULES
        self.assertFalse(unknown, f"Decide ownership before adding production modules {sorted(unknown)}. "
                         "Keep logic in its existing owner or update tests/test_architecture.py deliberately.")

    def test_production_imports_follow_ownership(self):
        errors = [error for path in sorted(MODULES)
                  for error in import_errors(path, (ROOT / path).read_text())]
        self.assertEqual(errors, [], "\n".join(errors))

    def test_guard_rejects_realistic_boundary_violations(self):
        examples = [
            ("app.py", "import sqlite3"),
            ("app.py", "from bs4 import BeautifulSoup"),
            ("app.py", "import requests"),
            ("scout.py", "from flask import Flask"),
            ("telegram_alerts.py", "import sqlite3"),
            ("scout.py", "from telegram_alerts import notify"),
            ("telegram_alerts.py", "from scout import Store"),
            ("scout.py", "import app"),
            ("telegram_alerts.py", "from app import create_app"),
            ("app.py", "from telegram_alerts import credentials as config"),
            ("app.py", "from scout import parse_search"),
            ("app.py", "import telegram_alerts as telegram"),
            ("app.py", "from scout import *"),
        ]
        for path, source in examples:
            with self.subTest(path=path, source=source):
                self.assertTrue(import_errors(path, source), f"Ownership guard missed {source!r} in {path}.")

    def test_discovery_includes_nested_untracked_production_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for path in ("app.py", "helpers/token.py", "tests/test_x.py", "scripts/check.py", ".venv/ignored.py"):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("")
            (root / ".gitignore").write_text(".venv/\n")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            self.assertEqual(production_paths(root), {"app.py", "helpers/token.py"})


if __name__ == "__main__":
    unittest.main()
