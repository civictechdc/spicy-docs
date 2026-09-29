"""The ``gao_recommendations`` table: every recommendation GAO's open-recommendations export has listed, as last listed.

GAO numbers its recommendations within each product and states the number at the end of the text, "(Recommendation 4)"
or "(Matter for Consideration 1)". The key (:data:`KEY_RULE`) is that number where the text states it: the product, the
kind, the number and the agency, the agency because one numbered recommendation made to three agencies is three records.
Only where no number is stated does the key fall back to the text. Measured on the 2026-09-28 export, 4,892 of its 5,379
records state a number and the rest key on their text, and both keys are unique (``docs/decisions.md``).

The export lists only open recommendations, so a host that keeps history holds every row it has seen and marks the ones
the latest export no longer lists; ``docs/decisions.md`` states that host's duties. The first-seen, last-seen and
listed-open columns are the host's; this shaper fills them for a record of the export it was read from.
"""

from __future__ import annotations

from datetime import date

from spicy_docs.schemas.tables import VALUE_KEY, Row, digest, flag, joined, table_contract, text

#: The key's rule, named in ``recommendation_id``'s sentence. A new rule is a new name and an explicit re-key.
KEY_RULE = "gao-recommendation-key/1"
#: The two kinds of numbered recommendation: one to an agency, and a matter for Congress to consider.
NUMBER_KINDS = ("recommendation", "matter")

GAO_RECOMMENDATIONS = table_contract(
    "gao_recommendations",
    grain=(
        "One row per recommendation per agency that GAO's open-recommendations export has listed, with its status as "
        "last listed."
    ),
    identity=("recommendation_id",),
    version_column="last_seen",
    key_spelling=VALUE_KEY,
    columns={
        "recommendation_id": (
            "The key, rule `gao-recommendation-key/1`: a digest of the lowercased publication number, the kind, the "
            "number GAO states and the agency; where the text states no number, of the number, the agency and the "
            "text, whitespace runs folded and case folded."
        ),
        "report_id": "The publication number lowercased: the GAO product id `gao_reports` is keyed on.",
        "publication_number": "The publication number exactly as GAO spells it, such as `GAO-26-108061`.",
        "publication_title": "The publication's title as the export states it, a line break GAO left in it included.",
        "publication_date": "The date GAO issued the publication, as an ISO date.",
        "director_name": (
            "The GAO director or directors the export names as the publication's contact, several joined by commas as "
            "GAO writes them, so a comma can also be part of one name (as in a suffix); NULL where it names none."
        ),
        "agency": (
            "The agency the recommendation is made to; a recommendation made to several agencies is one row for each."
        ),
        "recommendation": "The recommendation's text in full, the number GAO states at its end included.",
        "recommendation_kind": (
            "Which of GAO's numbered series the text's closing tag names: `recommendation` to an agency, or `matter` "
            "for Congress to consider; NULL where the text states no number."
        ),
        "recommendation_number": (
            "The number GAO states for it within its publication and kind, as GAO writes it; NULL where it states none."
        ),
        "status": "GAO's status for it as last listed: `Open` or `Open--Partially Addressed`.",
        "priority": "Whether GAO designates it a priority recommendation, as last listed: `true` or `false`.",
        "comments": "GAO's comments on the agency's progress as last listed, untrimmed; NULL where it states none.",
        "topics": "The topic the export files it under, as last listed; NULL where it states none.",
        "first_seen": (
            "The date the status-as-of stamp states on the first export read that listed it: when this table first saw "
            "it open, not when GAO made it."
        ),
        "last_seen": "The date the status-as-of stamp states on the latest export read that listed it.",
        "listed_open": (
            "Whether the latest export read lists it under this key. `false` says only that it is no longer listed: "
            "GAO closing it is the usual cause, but an edit to its number, text or agency, or a defective export, "
            "reads the same."
        ),
        "status_as_of": (
            "The export's own status-as-of stamp, verbatim, from the latest export that listed it; GAO labels it EST "
            "year round, though it is Eastern local time."
        ),
    },
)


def _fold(value: str) -> str:
    """Whitespace runs to one space and case folded: ``str.split`` also splits on the no-break spaces GAO writes."""
    return " ".join(value.split()).casefold()


def gao_recommendation_id(
    report_id: str, agency: str, recommendation: str, *, kind: str | None, number: str | None
) -> str:
    """The key under :data:`KEY_RULE`: ``sha256:`` over the stated number where there is one, else over the text.

    The two forms are prefixed ``number`` and ``text``, so no number key can equal a text key. The publication number is
    lowercased and the agency and text folded (:func:`_fold`): GAO respacing or recapitalising a field is the same
    recommendation, and measured on the 2026-09-28 export the fold merges no two records.
    """
    if (kind is None) != (number is None) or (kind is not None and kind not in NUMBER_KINDS):
        raise ValueError(f"a stated number needs one of {NUMBER_KINDS} and a number, or neither")
    if kind is not None and number is not None:
        parts = ("number", report_id.lower(), kind, number, _fold(agency))
    else:
        parts = ("text", report_id.lower(), _fold(agency), _fold(recommendation))
    identity = digest(joined(parts))
    assert identity is not None  # digest answers None only for a None input
    return identity


def shape_gao_recommendation(recommendation: object, *, status_as_of: str, as_of: date) -> Row:
    """One ``gao_recommendations`` row for a record of the export stamped ``status_as_of``, which lists it on ``as_of``.

    ``recommendation`` is a ``sources.gao.recommendations.GaoRecommendation``, read by attribute so this module stays a
    leaf. The director's phone is not published (owner decision, 2026-09-28).
    """
    seen = as_of.isoformat()
    return {
        "recommendation_id": gao_recommendation_id(
            recommendation.report_id,
            recommendation.agency,
            recommendation.recommendation,
            kind=recommendation.number_kind,
            number=recommendation.number,
        ),
        "report_id": text(recommendation.report_id),
        "publication_number": text(recommendation.publication_number),
        "publication_title": text(recommendation.publication_title),
        "publication_date": recommendation.publication_date.isoformat(),
        "director_name": text(recommendation.director_name),
        "agency": text(recommendation.agency),
        "recommendation": text(recommendation.recommendation),
        "recommendation_kind": text(recommendation.number_kind),
        "recommendation_number": text(recommendation.number),
        "status": text(recommendation.status),
        "priority": flag(recommendation.priority),
        "comments": text(recommendation.comments),
        "topics": text(recommendation.topics),
        "first_seen": seen,
        "last_seen": seen,
        "listed_open": flag(True),
        "status_as_of": text(status_as_of),
    }


__all__ = ["GAO_RECOMMENDATIONS", "KEY_RULE", "NUMBER_KINDS", "gao_recommendation_id", "shape_gao_recommendation"]
