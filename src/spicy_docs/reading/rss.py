"""Shared RSS 2.0 envelope reading: root/version, one channel, item elements, namespace-safe text.

Every keyless feed source built on this shape (the GAO reports feed, the
appropriations committee press-release feeds) restates the same three RSS 2.0
rules -- root ``<rss version="2.0">``, exactly one ``<channel>``, a bounded
list of ``<item>`` elements -- and the same single-required-child reading
rule, which must stay namespace-safe because extension fields such as
``dc:creator`` arrive in ``reading/xml.py``'s expanded ``{uri}local``
spelling. This module is that one restatement; each source keeps its own
field requirements and identity checks over the elements it returns.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from spicy_docs.reading.xml import parse_xml

DEFAULT_MAX_ITEMS = 1000


def read_rss2_channel(
    body: bytes,
    *,
    max_bytes: int,
    error_type: type[ValueError],
    label: str,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> tuple[Element, tuple[Element, ...]]:
    """Parse an RSS 2.0 document; return its one channel and item elements, in feed order."""
    root = parse_xml(body, max_bytes=max_bytes, error_type=error_type, label=label)
    if root.tag != "rss" or root.get("version") != "2.0":
        raise error_type(f"{label} is not an RSS 2.0 document")
    channels = [child for child in root if child.tag == "channel"]
    if len(channels) != 1:
        raise error_type(f"{label} requires exactly one channel")
    channel = channels[0]
    items = tuple(child for child in channel if child.tag == "item")
    if len(items) > max_items:
        raise error_type(f"{label} lists more items than supported")
    return channel, items


def single_child(element: Element, tag: str, *, error_type: type[ValueError], label: str) -> Element | None:
    """The one child with this tag, or ``None`` if it is absent; a repeated child refuses."""
    children = [child for child in element if child.tag == tag]
    if len(children) > 1:
        raise error_type(f"{label} repeats {tag}")
    return children[0] if children else None


def child_text(element: Element, tag: str, *, error_type: type[ValueError], label: str) -> str | None:
    """One child's stripped text, or ``None`` if it is absent or blank; a repeated child refuses."""
    child = single_child(element, tag, error_type=error_type, label=label)
    if child is None or child.text is None or not child.text.strip():
        return None
    return child.text.strip()
