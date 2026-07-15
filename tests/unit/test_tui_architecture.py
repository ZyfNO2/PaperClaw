import ast
from pathlib import Path


def test_tui_does_not_import_tools_repository_or_sqlite() -> None:
    tui_dir = Path(__file__).resolve().parents[2] / "src" / "paperclaw" / "tui"
    forbidden = ("paperclaw.tools", "paperclaw.context", "sqlite3")

    for path in tui_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(
            module == prefix or module.startswith(prefix + ".")
            for module in imported
            for prefix in forbidden
        ), f"forbidden TUI dependency in {path}: {imported}"
