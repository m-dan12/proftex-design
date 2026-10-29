"""docs/OWNERSHIP.md: все 17 задач на месте, ни один путь не закреплён за двумя задачами."""

import re
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "docs" / "OWNERSHIP.md"
ROW = re.compile(r"^\| (T\d\d) \| (.+) \|$")


def _rows() -> dict[str, list[str]]:
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            task, files = match.groups()
            # Пути после «кроме» — исключения из каталога владельца, а не его файлы.
            owned = files.split("кроме")[0]
            rows[task] = re.findall(r"`([^`]+)`", owned)
    return rows


def test_all_tasks_listed() -> None:
    assert sorted(_rows()) == [f"T{i:02d}" for i in range(1, 18)]


def test_no_path_owned_twice() -> None:
    seen: dict[str, str] = {}
    for task, paths in _rows().items():
        for path in paths:
            assert path not in seen, f"{path}: {seen[path]} и {task}"
            seen[path] = task
