"""Find duplication candidates without importing or executing the scanned code.

    UV_OFFLINE=1 uv run --frozen python -m tools.analysis.dry_audit \
        --root . --paths src tools --exclude tools/analysis/dry_audit.py > receipt.json

Exact means equal AST bodies, excluding docstrings/signatures/decorators. Shape
also replaces Name/argument identifiers in first-use order and masks literal
values by type; attributes and keyword names remain significant. Neither proves
equivalent behavior. Blocks are sliding windows of 3..6 adjacent statements in
every suite, including module scope. Contained matches with the same occurrence
coverage are suppressed. Overlapping retained candidates are counted once in
unique_lines, not in occurrence_lines. Single statements are covered by the
literal/regex/error inventories, not by the block detector.

Only Python files in the explicit paths are read. Syntax errors abort. Receipts
pin each input's bytes, Python version, thresholds and Git HEAD; they contain no
clock or absolute checkout paths. The tool opens no socket and needs only stdlib.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def _body(nodes):
    return [
        n
        for n in nodes
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
    ]


def _key(nodes, shape=False):
    names = {}

    def encode(value):
        if isinstance(value, ast.AST):
            if shape and isinstance(value, ast.Constant):
                return ("Constant", type(value.value).__name__)
            fields = []
            for name, field in ast.iter_fields(value):
                if shape and (
                    (isinstance(value, ast.Name) and name == "id") or (isinstance(value, ast.arg) and name == "arg")
                ):
                    field = names.setdefault(field, len(names))
                fields.append((name, encode(field)))
            return (type(value).__name__, fields)
        if isinstance(value, list):
            return [encode(v) for v in value]
        return value

    return hashlib.sha256(repr(encode(nodes)).encode()).hexdigest()


def _location(path, nodes, name=""):
    return {"path": path, "line": nodes[0].lineno, "end": nodes[-1].end_lineno, "name": name}


def _clusters(groups):
    result = []
    for key, occurrences in groups.items():
        locations = sorted({(o["path"], o["line"], o["end"], o["name"]) for o in occurrences})
        if len(locations) < 2:
            continue
        places = [dict(zip(("path", "line", "end", "name"), loc)) for loc in locations]
        result.append(
            {
                "key": key,
                "copies": len(places),
                "occurrence_lines": sum(p["end"] - p["line"] + 1 for p in places),
                "locations": places,
            }
        )
    return sorted(result, key=lambda g: (-g["occurrence_lines"], g["key"]))


def _maximal(groups):
    """Suppress windows fully covered by a larger match at every occurrence."""
    kept = []
    by_path = defaultdict(list)
    for group in groups:
        first = group["locations"][0]
        covered = False
        for previous in by_path[first["path"]]:
            if previous["copies"] != group["copies"]:
                continue
            if all(
                any(
                    p["path"] == q["path"] and p["line"] <= q["line"] and p["end"] >= q["end"]
                    for p in previous["locations"]
                )
                for q in group["locations"]
            ):
                covered = True
                break
        if not covered:
            kept.append(group)
            for path in {p["path"] for p in group["locations"]}:
                by_path[path].append(group)
    return kept


def _summary(groups):
    lines = set()
    places = set()
    for group in groups:
        for p in group["locations"]:
            places.add((p["path"], p["line"], p["end"]))
            lines.update((p["path"], line) for line in range(p["line"], p["end"] + 1))
    return {
        "clusters": len(groups),
        "unique_occurrences": len(places),
        "unique_lines": len(lines),
        "occurrence_lines": sum(g["occurrence_lines"] for g in groups),
    }


HELPER_TERMS = {
    "digest": r"sha256|hexdigest|file_digest",
    "date": r"fromisoformat|strptime|isoformat",
    "identity": r"bill_id|natural_key|system_code|package_id",
    "retry": r"retry|backoff|sleep\(",
    "credential": r"scrub_credential|read_api_key|CredentialRefused",
    "json": r"json\.dumps|json_column|canonical_json",
    "xml": r"itertext|findtext|parse_xml|scan_xml|\.findall\(",
    "page_span": r"bisect|page_offsets|span_start|span_end",
}


def scan(root: Path, paths: list[str], excludes=(), min_lines=4):
    files = set()
    for name in paths:
        path = root / name
        if not path.exists():
            raise ValueError(f"input does not exist: {name}")
        files.update(path.rglob("*.py") if path.is_dir() else [path])
    files = sorted(p for p in files if p.relative_to(root).as_posix() not in excludes)
    groups = {
        name: defaultdict(list)
        for name in (
            "exact_functions",
            "shape_functions",
            "exact_blocks",
            "shape_blocks",
            "literals",
            "regex",
            "errors",
        )
    }
    manifest, helpers, options = [], defaultdict(list), []
    function_count = eligible_functions = block_count = constant_count = regex_count = error_count = 0
    for path in files:
        raw = path.read_bytes()
        tree = ast.parse(raw, filename=str(path))
        source = raw.decode("utf-8")
        relative = path.relative_to(root).as_posix()
        manifest.append(
            {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "lines": len(source.splitlines())}
        )
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1
                body = _body(node.body)
                if body:
                    loc = _location(relative, body, node.name)
                    if loc["end"] - loc["line"] + 1 >= min_lines:
                        eligible_functions += 1
                        for shape, label in ((False, "exact_functions"), (True, "shape_functions")):
                            groups[label][_key(body, shape)].append(loc)
                    snippet = ast.get_source_segment(source, node) or ""
                    if loc["end"] - loc["line"] < 60:
                        for family, pattern in HELPER_TERMS.items():
                            if re.search(pattern, snippet):
                                helpers[family].append(loc)
                defaults = [*node.args.defaults, *node.args.kw_defaults]
                switches = sum(
                    isinstance(d, ast.Constant) and (d.value is None or isinstance(d.value, bool)) for d in defaults
                )
                if switches >= 3:
                    options.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "name": node.name,
                            "optional_or_bool_defaults": switches,
                        }
                    )
            for _, value in ast.iter_fields(node):
                if not isinstance(value, list) or not value or not all(isinstance(n, ast.stmt) for n in value):
                    continue
                suite = _body(value)
                for width in range(3, 7):
                    for start in range(len(suite) - width + 1):
                        block = suite[start : start + width]
                        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in block):
                            continue
                        loc = _location(relative, block)
                        if loc["end"] - loc["line"] + 1 < min_lines:
                            continue
                        block_count += 1
                        for shape, label in ((False, "exact_blocks"), (True, "shape_blocks")):
                            groups[label][_key(block, shape)].append(loc)
            if isinstance(node, ast.Constant) and id(node) not in docs:
                value = node.value
                if (isinstance(value, str) and len(value) >= 4) or (type(value) in (int, float) and abs(value) >= 2):
                    constant_count += 1
                    groups["literals"][repr(value)].append(_location(relative, [node]))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.args
                and node.func.attr
                in {"compile", "match", "fullmatch", "search", "finditer", "findall", "sub", "subn", "split"}
            ):
                pattern = node.args[0]
                if isinstance(pattern, ast.Constant) and isinstance(pattern.value, str):
                    regex_count += 1
                    groups["regex"][pattern.value].append(_location(relative, [node]))
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                message = node.exc.args[0]
                if isinstance(message, ast.JoinedStr):
                    template = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in message.values)
                elif isinstance(message, ast.Constant) and isinstance(message.value, str):
                    template = message.value
                else:
                    continue
                error_count += 1
                groups["errors"][template].append(_location(relative, [node]))
    clusters = {name: _clusters(group) for name, group in groups.items()}
    for name in ("exact_blocks", "shape_blocks"):
        clusters[name] = _maximal(clusters[name])
    return {
        "method": {
            "minimum_lines": min_lines,
            "block_widths": [3, 4, 5, 6],
            "paths": paths,
            "excludes": sorted(excludes),
            "python": sys.version.split()[0],
        },
        "inputs": manifest,
        "population": {
            "files": len(files),
            "lines": sum(m["lines"] for m in manifest),
            "functions": function_count,
            "eligible_functions": eligible_functions,
            "block_windows": block_count,
            "literal_occurrences": constant_count,
            "regex_occurrences": regex_count,
            "error_templates": error_count,
        },
        "summary": {name: _summary(group) for name, group in clusters.items()},
        "clusters": clusters,
        "small_helpers": dict(helpers),
        "optional_parameter_candidates": sorted(options, key=lambda o: -o["optional_or_bool_defaults"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--paths", nargs="+", default=["src", "tools"])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--min-lines", type=int, default=4)
    args = parser.parse_args(argv)
    if args.min_lines < 1:
        parser.error("--min-lines must be positive")
    result = scan(args.root.resolve(), args.paths, args.exclude, args.min_lines)
    result["tool_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["git_head"] = subprocess.check_output(["git", "-C", str(args.root), "rev-parse", "HEAD"], text=True).strip()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
