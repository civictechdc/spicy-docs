"""The dry-audit diagnostic must find edited copies without treating every shape as equal.

Pins exact and shape function clusters with their locations, literal, regex and
error inventories excluding docstrings, short-helper and repeated-binding
rules, and input validation.
"""

import pytest

from tools.analysis.dry_audit import scan


def test_copies_shapes_blocks_and_false_friends(tmp_path):
    """Exact and shape copies cluster with their locations while false friends stay apart."""
    original = '''def original(value):
    """Not executable code."""
    result = value.strip()
    if result:
        result = result.lower()
    return result
'''
    (tmp_path / "a.py").write_text(original)
    (tmp_path / "b.py").write_text(
        original.replace("original", "other").replace("Not executable code.", "Different prose.")
    )
    (tmp_path / "c.py").write_text(original.replace("value", "item").replace("result", "answer"))
    (tmp_path / "d.py").write_text(original.replace("lower", "upper"))
    (tmp_path / "e.py").write_text("""def partial(value):
    print("extra")
    result = value.strip()
    if result:
        result = result.lower()
    return result
""")
    result = scan(tmp_path, ["."])
    exact = result["clusters"]["exact_functions"]
    shape = result["clusters"]["shape_functions"]
    assert result["population"]["functions"] == 5
    assert len(exact) == 1 and exact[0]["copies"] == 2
    assert len(shape) == 1 and shape[0]["copies"] == 3
    assert {p["path"] for p in result["clusters"]["shape_blocks"][0]["locations"]} == {"a.py", "b.py", "c.py", "e.py"}
    assert exact[0]["locations"][0]["line"] == 3
    assert result["summary"]["exact_functions"]["unique_lines"] == 8
    assert result == scan(tmp_path, ["."])


def test_inventory_excludes_docstrings_but_keeps_patterns_and_error_shapes(tmp_path):
    """The inventory excludes docstrings but keeps literals, regex patterns and error shapes, and refuses bad inputs."""
    source = '''"""Repeated docs are not code."""
import re
PATTERN = re.compile(r"[0-9]{4}")
LIMIT = 1024
def check(value):
    raise ValueError(f"invalid value: {value}")
'''
    (tmp_path / "a.py").write_text(source)
    (tmp_path / "b.py").write_text(source.replace("{value}", "{str(value)}"))
    (tmp_path / "skip.py").write_text("not Python!")
    result = scan(tmp_path, ["."], ["skip.py"])
    assert result["population"]["files"] == 2
    assert result["clusters"]["regex"][0]["key"] == "[0-9]{4}"
    assert result["clusters"]["errors"][0]["key"] == "invalid value: {}"
    assert "'Repeated docs are not code.'" not in {g["key"] for g in result["clusters"]["literals"]}
    assert {g["key"] for g in result["clusters"]["literals"]} >= {"1024", "'[0-9]{4}'"}
    with pytest.raises(SyntaxError):
        scan(tmp_path, ["."])
    with pytest.raises(ValueError, match="input does not exist"):
        scan(tmp_path, ["missing"])


def test_short_helpers_literal_changes_and_repeated_bindings(tmp_path):
    """Short helpers are excluded by line count, while a literal change and a repeated binding create their own
    clusters.
    """
    (tmp_path / "a.py").write_text('def a(x):\n    return x.get("first", x)\n')
    (tmp_path / "b.py").write_text('def b(y):\n    return y.get("second", y)\n')
    (tmp_path / "c.py").write_text('def c(y, z):\n    return y.get("second", z)\n')
    assert scan(tmp_path, ["."])["summary"]["shape_functions"]["clusters"] == 0
    result = scan(tmp_path, ["."], min_lines=1)
    assert result["summary"]["exact_functions"]["clusters"] == 0
    assert result["summary"]["shape_functions"]["clusters"] == 1
    assert result["clusters"]["shape_functions"][0]["copies"] == 2
    pin = result["inputs"][0]["sha256"]
    (tmp_path / "a.py").write_text('def a(x):\n    return x.get("changed", x)\n')
    assert scan(tmp_path, ["."], min_lines=1)["inputs"][0]["sha256"] != pin
