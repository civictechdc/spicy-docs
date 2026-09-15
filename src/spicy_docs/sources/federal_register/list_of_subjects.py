"""Read the Federal Register's printed List of Subjects from retained text.

These readers return normalized block text and structural observations. Keep
the original body and its source identity separately. Vocabulary resolution
belongs to the consumer. Grammar and bounds come from the SpicySearch reader
and its named publisher regression cases; acquisition is a separate operation.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence

__all__ = [
    "SUBHEADING_SCAN_GAP",
    "extract_blocks_from_text_body",
    "extract_blocks_from_xml_body",
    "inspect_text_body",
    "is_cfr_subheading",
    "printed_cfr_subheadings",
    "split_printed_atoms",
    "strip_markup",
    "unread_subheading_candidate",
]

_LSTSUB = re.compile("<LSTSUB\\b[^>]*>(.*?)</LSTSUB>", re.DOTALL | re.IGNORECASE)
_PARAGRAPH = re.compile("<P\\b[^>]*>(.*?)</P>", re.DOTALL | re.IGNORECASE)
_SCRIPT_OR_STYLE = re.compile("<(script|style)\\b[^>]*>.*?</\\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile("<[^>]*>")
# A page break inside a term joins lines; after sentence punctuation it preserves a paragraph.
_PAGE_MARKER = re.compile("(?P<prev>\\S)?[ \\t]*\\n*[ \\t]*\\[\\[Page [^\\]]*\\]\\][ \\t]*\\n*")
_SENTENCE_TERMINATORS = ".:;"
_HEADING = re.compile("^[ \\t]*Lists? of Subjects?\\b", re.MULTILINE)
_CFR_OPENING = re.compile("^\\d+\\s+CFR\\b", re.IGNORECASE)
_ROMAN = re.compile("^[IVXLCDM]+$")
_WORDS = re.compile("(?<!\\d)[A-Za-z]+(?!\\d)")
_CFR_HEADING_WORDS = frozenset(
    {
        "cfr",
        "part",
        "parts",
        "chapter",
        "chapters",
        "subchapter",
        "subchapters",
        "subtitle",
        "subpart",
        "subparts",
        "appendix",
        "appendices",
        "and",
        "through",
        "to",
    }
)
_BLANK_LINE = re.compile("\\n[ \\t]*\\n")


def strip_markup(payload: str) -> str:
    """Remove scripts and tags, then decode entities in retained publisher text."""
    without_scripts = _SCRIPT_OR_STYLE.sub(" ", payload)
    return html.unescape(_TAG.sub("", without_scripts))


def extract_blocks_from_xml_body(payload: str) -> tuple[str, ...]:
    """Read every P inside LSTSUB, excluding HD part headings; preserve paragraph order."""
    blocks: list[str] = []
    for element in _LSTSUB.findall(payload):
        for paragraph in _PARAGRAPH.findall(element):
            text = _collapse(strip_markup(paragraph))
            if text:
                blocks.append(text)
    return tuple(blocks)


def _prepare_text_body(payload: str) -> str:
    """Normalize carrier markup and page furniture once for both text scans."""
    return _PAGE_MARKER.sub(_page_marker_replacement, strip_markup(payload))


def extract_blocks_from_text_body(payload: str) -> tuple[str, ...]:
    """Read printed List(s) of Subjects blocks using the observed paragraph grammar."""
    return _extract_blocks_from_prepared_text(_prepare_text_body(payload))


def _extract_blocks_from_prepared_text(text: str) -> tuple[str, ...]:
    """Read term paragraphs, including fused headings, agency labels and wrapped lines."""
    blocks: list[str] = []
    consumed_to = 0
    for heading in _HEADING.finditer(text):
        if heading.start() < consumed_to:
            continue
        paragraphs = _paragraphs_after(text, heading.start())
        if not paragraphs:
            continue
        head, rest = (paragraphs[0], _expand_fused_paragraphs(paragraphs[1:]))
        cursor = 0
        agency_labeled = False
        head_first_line, _, head_remainder = head[0].partition("\n")
        # Only the first line is the heading; a glued remainder may contain the actual terms.
        if "CFR" in head_first_line:
            if head_remainder.strip() and (not _looks_like_a_heading_continuation(head_remainder)):
                blocks.append(_collapse(head_remainder))
            elif rest and (not _is_subject_subheading(rest[0][0])):
                block, cursor = _read_wrapped_terms(rest, 0)
                blocks.append(block)
        else:
            if head_remainder.strip() and _split_embedded_subheading(head_remainder.strip()) is not None:
                rest = _expand_fused_paragraphs([(head_remainder.strip(), head[1])]) + rest
            if rest and (not _is_subject_subheading(rest[0][0])):
                if _is_interstitial_subject_label(rest, 0):
                    agency_labeled = True
                    cursor = 1
                else:
                    block, cursor = _read_wrapped_terms(rest, 0)
                    blocks.append(block)
        while cursor < len(rest):
            if agency_labeled and _is_interstitial_subject_label(rest, cursor):
                cursor += 1
                continue
            if not _is_subject_subheading(rest[cursor][0]):
                break
            if cursor + 1 >= len(rest):
                break
            if _is_subject_subheading(rest[cursor + 1][0]):
                cursor += 1
                continue
            if agency_labeled and _is_interstitial_subject_label(rest, cursor + 1):
                cursor += 2
                continue
            block, cursor = _read_wrapped_terms(rest, cursor + 1)
            blocks.append(block)
        # Consume only read paragraphs so another heading in the window remains reachable.
        consumed_to = rest[cursor - 1][1] if cursor else paragraphs[0][1]
    return tuple(block for block in blocks if block)


# One terms paragraph normally separates subheadings; a longer gap ends the scan.
SUBHEADING_SCAN_GAP = 2


def printed_cfr_subheadings(payload: str) -> tuple[str, ...]:
    """Read printed CFR subheadings in block order, retaining duplicates.

    Bare Part headings without CFR remain outside this structural check."""
    return _printed_cfr_subheadings_from_prepared_text(_prepare_text_body(payload))


def _printed_cfr_subheadings_from_prepared_text(text: str) -> tuple[str, ...]:
    """Stop after the configured gap beyond the final printed subject subheading."""
    printed: list[str] = []
    scanned_to = 0
    for heading in _HEADING.finditer(text):
        if heading.start() < scanned_to:
            continue
        gap = 0
        for paragraph, end in _expand_fused_paragraphs(_paragraphs_after(text, heading.start())):
            scanned_to = max(scanned_to, end)
            if is_cfr_subheading(paragraph):
                printed.append(_collapse(paragraph))
                gap = 0
                continue
            gap += 1
            if gap > SUBHEADING_SCAN_GAP:
                break
    return tuple(printed)


def inspect_text_body(payload: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return blocks and printed CFR subheadings after one markup cleanup."""
    text = _prepare_text_body(payload)
    return (_extract_blocks_from_prepared_text(text), _printed_cfr_subheadings_from_prepared_text(text))


def unread_subheading_candidate(payload: str) -> bool:
    """Flag more printed subheadings than recovered blocks.

    This is a review candidate, not proof of missing terms: empty parts can trigger it."""
    blocks, subheadings = inspect_text_body(payload)
    return len(subheadings) > len(blocks)


def _page_marker_replacement(match: re.Match[str]) -> str:
    previous = match.group("prev")
    if previous is None:
        return ""
    return previous + ("\n\n" if previous in _SENTENCE_TERMINATORS else "\n")


def _is_cfr_heading_word(word: str) -> bool:
    """Admit CFR heading words, Roman numerals and uppercase appendix letters."""
    return word.lower() in _CFR_HEADING_WORDS or bool(_ROMAN.match(word)) or (len(word) == 1 and word.isupper())


def is_cfr_subheading(paragraph: str) -> bool:
    """Recognize a bare CFR reference paragraph; reject reference-shaped prose."""
    text = paragraph.strip()
    if len(text) > 200 or not _CFR_OPENING.match(text):
        return False
    return all(_is_cfr_heading_word(word) for word in _WORDS.findall(text))


_SUBJECT_UNIT = re.compile("(?:\\b(?:sub)?parts?\\b|\\bappend(?:ix|ices)\\b|^\\d+\\s+CFR\\s+\\d)", re.IGNORECASE)
_INTERSTITIAL_SUBJECT_LABELS = frozenset({"Board", "FDIC", "OCC", "OTS"})
_WRAPPED_TERM_CONJUNCTIONS = frozenset({"and", "or"})
_LAST_WORD = re.compile("([A-Za-z]+)\\W*$")
_POST_SUBJECTS_BOUNDARY = re.compile(
    "^(?:PART\\s+\\d+\\b|Authority\\s*:|Authority\\s+and\\s+Issuance\\s*$|Dated\\s*:|For\\s+the\\s+reasons\\b|In\\s+consideration\\s+of\\b|Accordingly\\b|Therefore\\b)",
    re.IGNORECASE,
)


def _is_subject_subheading(paragraph: str) -> bool:
    """Read parts and appendices; chapter-only headings introduce amendatory prose."""
    return is_cfr_subheading(paragraph) and bool(_SUBJECT_UNIT.search(paragraph.strip()))


def _is_interstitial_subject_label(paragraphs: Sequence[tuple[str, int]], index: int) -> bool:
    """Admit the four observed agency labels only before a real part heading.

    Examples 95-16563 and 95-18098 establish the closed set and look-ahead."""
    if index + 1 >= len(paragraphs):
        return False
    label = paragraphs[index][0].strip()
    return label in _INTERSTITIAL_SUBJECT_LABELS and _is_subject_subheading(paragraphs[index + 1][0])


def _read_wrapped_terms(paragraphs: Sequence[tuple[str, int]], index: int) -> tuple[str, int]:
    """Join wrapped lists only when punctuation or a continuation proves the join.

    Explicit post-list headings and completed sentences stop the scan."""
    pieces = [paragraphs[index][0]]
    has_list_separator = any(mark in pieces[0] for mark in ",;")
    cursor = index + 1
    while cursor < len(paragraphs):
        following = paragraphs[cursor][0]
        if is_cfr_subheading(following) or _POST_SUBJECTS_BOUNDARY.match(following.strip()):
            break
        previous = pieces[-1].rstrip()
        if previous.endswith((".", "?", "!")):
            break
        previous_word_match = _LAST_WORD.search(previous)
        previous_word = previous_word_match.group(1).casefold() if previous_word_match else ""
        following_starts_lowercase = following.lstrip()[:1].islower()
        proves_continuation = (
            previous.endswith((",", ";", "-"))
            or previous_word in _WRAPPED_TERM_CONJUNCTIONS
            or (has_list_separator and following_starts_lowercase)
        )
        if not proves_continuation:
            break
        pieces.append(following)
        has_list_separator = has_list_separator or any(mark in following for mark in ",;")
        cursor += 1
    return (_collapse("\n".join(pieces)), cursor)


def _looks_like_a_heading_continuation(text: str) -> bool:
    """Recognize wrapped part numbers, not terms (98-4853 names eighteen parts)."""
    return all(_is_cfr_heading_word(word) for word in _WORDS.findall(text))


def _split_embedded_subheading(paragraph: str) -> tuple[str, str] | None:
    """Split at a CFR heading on any line, preserving complete wrapped headings.

    Fused shapes occur in 97-23498, 95-21571 and 96-21860."""
    if is_cfr_subheading(paragraph):
        return None
    lines = paragraph.split("\n")
    if len(lines) < 2:
        return None
    for index, line in enumerate(lines):
        if not is_cfr_subheading(line.strip()):
            continue
        before = "\n".join(lines[:index]).strip()
        if before:
            return (before, "\n".join(lines[index:]).strip())
        after = "\n".join(lines[index + 1 :]).strip()
        if after:
            return (line.strip(), after)
    return None


def _expand_fused_paragraphs(paragraphs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Split fused headings and terms while retaining each original paragraph end."""
    expanded: list[tuple[str, int]] = []
    for text, end in paragraphs:
        split = _split_embedded_subheading(text)
        if split is None:
            expanded.append((text, end))
        else:
            expanded.extend(_expand_fused_paragraphs([(split[0], end), (split[1], end)]))
    return expanded


# Preserve the established window: the widest observed example (2023-27908) needs 59 paragraphs.
_MAX_PARAGRAPHS = 200
_WINDOW_CHARACTERS = 120000


def _paragraphs_after(text: str, start: int) -> list[tuple[str, int]]:
    """Read bounded paragraphs with monotonic end positions used only for scan progress."""
    window = text[start : start + _WINDOW_CHARACTERS]
    kept: list[tuple[str, int]] = []
    offset = 0
    for piece in _BLANK_LINE.split(window):
        end = offset + len(piece)
        stripped = piece.strip()
        if stripped:
            kept.append((stripped, start + end))
            if len(kept) >= _MAX_PARAGRAPHS:
                break
        offset = end + 2
    return kept


def _collapse(value: str) -> str:
    return " ".join(value.split())


_SENTENCE_END = re.compile("(?<![A-Z])(?<!U\\.S)\\.\\s")
_LEADING_CONJUNCTION = re.compile("^(?:and|&)\\s+", re.IGNORECASE)
_ATOM_SEPARATOR = re.compile("[,;]")


def split_printed_atoms(block: str) -> tuple[str, ...]:
    """Read comma/semicolon atoms through the first sentence, retaining abbreviations.

    Remove serial conjunctions. Atoms are not resolved vocabulary terms."""
    body = _collapse(block)
    sentence_end = _SENTENCE_END.search(body)
    if sentence_end is not None:
        body = body[: sentence_end.start()]
    body = body.rstrip(".").strip()
    atoms = (_LEADING_CONJUNCTION.sub("", atom.strip()).strip() for atom in _ATOM_SEPARATOR.split(body))
    return tuple(atom for atom in atoms if atom)
