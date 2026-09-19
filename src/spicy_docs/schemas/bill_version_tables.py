"""One bill version's row, and one row per content-bearing node inside it.

Two changes from the placement study, both made because spicy-regs publishes
one Parquet object per table read through a DuckDB view:

* ``bill_versions`` carries no ``text`` and no ``xml`` column (C2).  A full-text
  column per version is a multi-GB object fighting the shrink guard, and
  BillTrax itself listed both in ``METADATA_STRIP_COLUMNS``.  Nothing is lost:
  ``sha256``, ``byte_size``, ``package_id`` and ``resolved_url`` say exactly
  which bytes were read, ``bill_sections.body`` carries the text at the grain
  people query, and the body recomposes from its sections.
* ``bill_sections`` is keyed ``(bill_id, version_code, source, match_path,
  body_index)`` (C4).  A reported bill carries two ``legis-body`` elements and
  DeltaTrack's ``BillNode`` exposes ``body_index`` precisely because match paths
  repeat across them; ``source`` is part of the parent version's own key.

``bill_versions`` also carries the GPO PDF cleanup counts as *processing*
provenance rather than data, modelled on spicy-regs's own
``pdf_extraction_results_json``: a row says what the normalizer did to the bytes
before anything read them.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import (
    Row,
    digest,
    flag,
    joined,
    json_column,
    table_contract,
    text,
)
from spicy_docs.schemas.tables import bill_id as bill_key

BILL_VERSIONS = table_contract(
    "bill_versions",
    grain="One row per printing of a bill, per source that supplied it.",
    identity=("bill_id", "version_code", "source"),
    version_column="version_date",
    columns={
        "bill_id": "The bill this printing belongs to.",
        "version_code": "The sealed version-code slug BillTrax stores and this repository never renames.",
        "source": "Which acquisition path supplied this row (govinfo, congress, govinfo-pdf, upload).",
        "label": "The publisher's version-type string verbatim, which is not unique per printing.",
        "version_date": "The publisher's date for this printing; the merge prefers the larger value.",
        "package_id": "The GovInfo BILLS package id, read from a stated format URL rather than derived by name.",
        "format_name": "Which rendition was read (xml, txt, pdf, html, uslm), as choose_format named it.",
        "format_type": "The publisher's own format type string on the chosen link, where it states one.",
        "requested_url": "The URL the fetch asked for.",
        "resolved_url": "The URL the response actually came from, which a redirect can change.",
        "content_type": "The response Content-Type exactly as the publisher sent it.",
        "byte_size": "Length in bytes of the captured body, before any decoding.",
        "sha256": "Digest of the captured body bytes, spelled sha256: plus the hex digest.",
        "observed_at": "When the body was captured; the instant the other capture columns describe.",
        "offered_formats_json": "Every format link the publisher offered for this printing, as a JSON array.",
        "version_code_is_reprint_ambiguous": (
            "True when the publisher's version-type string also names a numbered reprint, "
            "so the slug alone cannot tell the two printings apart."
        ),
        "root_tag": "The XML root element name (bill, resolution, amendment-doc).",
        "body_tags": "The body element names found, unit-separator joined; a reported bill states two.",
        "publisher_stage": "The root's own bill-stage or resolution-stage attribute: the publisher's word for it.",
        "section_count": "How many content-bearing nodes the flattening produced; the bill_sections row count.",
        "discarded_elements_json": (
            "Count by element name of every element whose text survives nowhere in the flattened nodes."
        ),
        "equivalent_xml_version_code": "For a PDF twin, the version_code of the XML row it stands in for.",
        "equivalent_xml_source": (
            "That twin's source.  A version code is not unique across acquisition paths, which is why "
            "bill_versions keys on source too, so a twin reference needs both halves to resolve."
        ),
        "cleanup_line_numbers": "GPO PDF normalization: whether per-line gutter numbering was detected and stripped.",
        "cleanup_gpo_footers": "GPO PDF normalization: whether VerDate print-metadata footers were stripped.",
        "cleanup_spacing_normalized": "GPO PDF normalization: the collapse rule always runs, kept for parity.",
        "cleanup_small_caps_merges": "GPO PDF normalization: how many lone-uppercase-letter lines were merged.",
        "cleanup_hyphen_rejoins": "GPO PDF normalization: how many gutter-corroborated hyphen wraps were rejoined.",
        "cleanup_json": "The per-page GPO cleanup breakdown, including which evidence gated bare-digit stripping.",
        "kind": (
            "Interpreted document kind: `full_text`, `kind_uncertain` (a full-text slug whose document is "
            "too thin to be sure), `procedural_amendments`, `procedural_summary`, or `unknown`."
        ),
        "kind_rule": (
            "Which version-kind rule fired, as the classifier names them: `procedural_amendments_slug`, "
            "`procedural_summary_slug`, `full_text_slug`, `full_text_slug_thin` (a full-text slug the size "
            "heuristic demoted to kind_uncertain), `amendment_substring` (an unlisted slug this "
            "repository's own heuristic caught), `size_heuristic` (an unlisted slug a large body promoted "
            "to full_text), or `unknown` when nothing claimed it."
        ),
        "kind_label": "The display label for this kind, supplied by the caller that owns the vocabulary.",
        "kind_warning": (
            "The inline warning this kind carries, for a version picker.  NULL for `full_text` and for "
            "`unknown`, which states none of its own."
        ),
        "kind_section_count": "The section count the kind heuristic was given, recorded so the answer re-derives.",
        "kind_body_bytes": "The body byte length the kind heuristic was given, recorded for the same reason.",
    },
)

BILL_SECTIONS = table_contract(
    "bill_sections",
    grain="One row per content-bearing node of one bill version, in document order.",
    identity=("bill_id", "version_code", "source", "match_path", "body_index"),
    version_column="version_date",
    columns={
        "bill_id": "The bill this section belongs to.",
        "version_code": "The printing this section was read from.",
        "source": "Which acquisition path supplied the printing; part of the parent version's key.",
        "match_path": "The normalized, division-free cross-version key, unit-separator joined.",
        "match_path_json": "The same path as a JSON array, so a consumer need not split on a separator.",
        "display_path_json": "The human-facing path the engine composes, as a JSON array.",
        "element_id": "The publisher's own id attribute on the element this node came from.",
        "section_number": "The section's own number as displayed (Sec. 1), where it has one.",
        "heading": "The section's header text, empty where the node carries none.",
        "body": "The section's body text, at the grain people actually query.",
        "display_text": "The engine's display rendering of the body, kept apart from the body itself.",
        "division_label": "The division this section sits under, as the engine composes the label.",
        "division_key": "The normalized division key, which is what a cross-version match ignores.",
        "body_index": "Which body element this node came from; a reported bill carries two.",
        "seq": "Position in document order, which the match path deliberately does not encode.",
        "body_chars": "Character length of body.",
        "body_sha256": "Digest of body's UTF-8 bytes, so an unchanged section is recognisable without a join.",
        "version_date": "The parent printing's date, carried so this table versions with its parent.",
    },
)


def _format_link(item: object) -> dict[str, object]:
    return {"url": item.url, "type": item.type, "package_id": item.package_id}


def _page_cleanup(page: object) -> dict[str, object]:
    return {
        "page": page.page,
        "verdate_footer_lines": page.verdate_footer_lines,
        "footer_continuation_lines": page.footer_continuation_lines,
        "dsk_user_lines": page.dsk_user_lines,
        "running_footer_lines": page.running_footer_lines,
        "bare_page_number_lines": page.bare_page_number_lines,
        "bare_page_number_evidence": page.bare_page_number_evidence,
        "bullet_bill_lines": page.bullet_bill_lines,
        "content_lines": page.content_lines,
        "small_caps_merges": page.small_caps_merges,
        "hyphen_rejoin_count": page.hyphen_rejoin_count,
    }


def shape_bill_version(
    capture: object,
    *,
    identity: object,
    kind: object,
    kind_label: str | None = None,
    kind_warning: str | None = None,
) -> Row:
    """One ``bill_versions`` row from one acquired printing and its kind finding.

    ``capture`` is an ``interpretation.bill_family.BillVersionCapture``, read by
    attribute so this module stays a leaf.  ``kind_label`` and ``kind_warning``
    come from ``interpretation.version_kind``'s own label tables and are passed
    in for the same reason.
    """
    version = capture.version
    body = capture.body
    document = capture.document
    cleanup = capture.cleanup
    return {
        "bill_id": bill_key(identity),
        "version_code": text(capture.version_code),
        "source": text(capture.source),
        "label": text(version.type),
        "version_date": text(version.date),
        "package_id": text(capture.package_id),
        "format_name": text(capture.format_name),
        "format_type": text(None if capture.chosen_format is None else capture.chosen_format.type),
        "requested_url": text(None if body is None else body.requested_url),
        "resolved_url": text(None if body is None else body.resolved_url),
        "content_type": text(None if body is None else body.content_type),
        "byte_size": text(None if body is None else body.byte_size),
        "sha256": text(None if body is None else body.sha256),
        "observed_at": text(None if body is None else body.observed_at),
        "offered_formats_json": json_column([_format_link(item) for item in version.formats]),
        "version_code_is_reprint_ambiguous": flag(capture.version_code_is_reprint_ambiguous),
        "root_tag": text(None if document is None else document.root_tag),
        "body_tags": None if document is None else joined(document.body_tags),
        "publisher_stage": text(None if document is None else document.stage),
        "section_count": text(None if document is None else len(document.sections)),
        "discarded_elements_json": (None if document is None else json_column(dict(document.discarded_elements))),
        "equivalent_xml_version_code": text(capture.equivalent_xml_version_code),
        "equivalent_xml_source": text(capture.equivalent_xml_source),
        "cleanup_line_numbers": flag(None if cleanup is None else cleanup.line_numbers),
        "cleanup_gpo_footers": flag(None if cleanup is None else cleanup.gpo_footers),
        "cleanup_spacing_normalized": flag(None if cleanup is None else cleanup.spacing_normalized),
        "cleanup_small_caps_merges": text(None if cleanup is None else cleanup.small_caps_merges),
        "cleanup_hyphen_rejoins": text(None if cleanup is None else cleanup.hyphen_rejoin_count),
        "cleanup_json": (None if cleanup is None else json_column([_page_cleanup(page) for page in cleanup.pages])),
        "kind": text(kind.kind),
        "kind_rule": text(kind.rule),
        "kind_label": text(kind_label),
        "kind_warning": text(kind_warning),
        "kind_section_count": text(kind.section_count),
        "kind_body_bytes": text(kind.body_bytes),
    }


def shape_bill_section(
    node: object,
    *,
    bill_id: str,
    version_code: str,
    source: str,
    seq: int,
    version_date: str | None,
) -> Row:
    """One ``bill_sections`` row from one DeltaTrack ``BillNode``."""
    body = node.body_text or ""
    return {
        "bill_id": bill_id,
        "version_code": text(version_code),
        "source": text(source),
        "match_path": joined(node.match_path),
        "match_path_json": json_column(list(node.match_path)),
        "display_path_json": json_column(list(node.display_path)),
        "element_id": text(node.element_id) or None,
        "section_number": text(node.section_number),
        "heading": text(node.header_text),
        "body": text(body),
        "display_text": text(node.display_text),
        "division_label": text(node.division_label),
        "division_key": text(node.division_key),
        "body_index": text(node.body_index),
        "seq": text(seq),
        "body_chars": text(len(body)),
        "body_sha256": digest(body),
        "version_date": text(version_date),
    }


__all__ = [
    "BILL_SECTIONS",
    "BILL_VERSIONS",
    "shape_bill_section",
    "shape_bill_version",
]
