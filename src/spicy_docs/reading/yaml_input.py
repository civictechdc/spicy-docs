"""Read bounded, string-keyed source YAML with literal dates and unambiguous fields."""

from __future__ import annotations

from typing import ClassVar

from spicy_docs.transport.source_acquirer import check_payload

# Values JSON cannot hold, and dates that would stop being their source text.
# An explicit tag (``!!timestamp 2026-09-28``, ``!!binary``) is refused rather
# than constructed, so the literal-date promise holds for tagged values too.
_REFUSED_TAGS = frozenset(f"tag:yaml.org,2002:{name}" for name in ("timestamp", "binary", "set", "omap", "pairs"))


def load_bounded_yaml(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    max_bytes: int,
    max_nodes: int = 250_000,
    max_depth: int = 16,
) -> object:
    """Preserve date text; require string keys and refuse aliases, duplicates and merges.

    The caller owns the source shape and retains the original bytes. This
    reader does not turn YAML into canonical artifact bytes or trust a filename.
    """
    check_payload(raw, max_bytes, label=source, error_type=error_type)
    if type(max_nodes) is not int or max_nodes <= 0 or type(max_depth) is not int or max_depth <= 0:
        raise error_type(f"{source} node and depth bounds must be positive integers")
    try:
        import yaml
    except ImportError as error:
        raise error_type("install spicy-docs[yaml] to read source YAML") from error

    class SourceLoader(yaml.SafeLoader):
        yaml_implicit_resolvers: ClassVar[dict] = {
            key: [(tag, regex) for tag, regex in values if tag not in _REFUSED_TAGS]
            for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }
        yaml_constructors: ClassVar[dict] = {
            tag: constructor
            for tag, constructor in yaml.SafeLoader.yaml_constructors.items()
            if tag not in _REFUSED_TAGS
        }

    loader = None
    try:
        loader = SourceLoader(raw)
        node = loader.get_single_node()
        stack = [(node, 0)] if node is not None else []
        seen: set[int] = set()
        while stack:
            item, depth = stack.pop()
            if id(item) in seen:
                raise error_type(f"{source} uses YAML aliases")
            if depth > max_depth or len(seen) >= max_nodes:
                raise error_type(f"{source} exceeds its node/depth bounds")
            seen.add(id(item))
            if isinstance(item, yaml.MappingNode):
                keys = [key.value for key, _ in item.value if isinstance(key, yaml.ScalarNode)]
                if len(keys) != len(item.value) or len(set(keys)) != len(keys) or "<<" in keys:
                    raise error_type(f"{source} has duplicate, merged or complex keys")
                # JSON-shaped source records need string keys at every level.
                # Otherwise e.g. 0xA and "10" survive YAML as distinct keys but
                # collapse when retained as JSON, losing an unknown field.
                decoded = [loader.construct_object(key) for key, _ in item.value]
                if any(not isinstance(key, str) for key in decoded):
                    raise error_type(f"{source} requires string mapping keys")
                stack.extend((child, depth + 1) for pair in item.value for child in pair)
            elif isinstance(item, yaml.SequenceNode):
                stack.extend((child, depth + 1) for child in item.value)
        return loader.construct_document(node) if node is not None else None
    except (yaml.YAMLError, UnicodeError, RecursionError, ValueError) as error:
        if isinstance(error, error_type):
            raise
        raise error_type(f"{source} is not supported YAML") from error
    finally:
        if loader is not None:
            loader.dispose()
