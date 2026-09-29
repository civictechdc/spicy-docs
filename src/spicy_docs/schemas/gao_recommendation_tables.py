"""The ``gao_recommendations`` table: every recommendation GAO's open-recommendations export has listed, as last listed.

GAO states no recommendation id, so the key is a digest of the three fields that tell one row from another: the
publication, the agency and the recommendation's text. Measured on the 2026-09-28 export (5,379 records), those three are
unique and publication plus text alone are not: one recommendation made to three agencies is three records.

The export lists only open recommendations, so a host that keeps history holds every row it has seen and marks the ones
the latest export no longer lists (spicy-regs does, in ``build_gao_recommendations``). The first-seen, last-seen and
listed-open columns are that host's; this shaper fills them for a record the export it was read from lists.
"""

from __future__ import annotations

from datetime import date

from spicy_docs.schemas.tables import VALUE_KEY, Row, digest, flag, joined, table_contract, text

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
            "Digest of the lowercased publication number, the agency and the recommendation text, each with its "
            "whitespace runs folded to one space; GAO states no id of its own."
        ),
        "report_id": "The publication number lowercased: the GAO product id `gao_reports` is keyed on.",
        "publication_number": "The publication number exactly as GAO spells it, such as `GAO-26-108061`.",
        "publication_title": "The publication's title as the export states it, a line break GAO left in it included.",
        "publication_date": "The date GAO issued the publication, as an ISO date.",
        "director_name": "The GAO director the export names as the publication's contact; NULL where it names none.",
        "agency": (
            "The agency the recommendation is made to; a recommendation made to several agencies is one row for each."
        ),
        "recommendation": "The recommendation's text in full.",
        "status": "GAO's status for it as last listed: `Open` or `Open--Partially Addressed`.",
        "priority": "Whether GAO designates it a priority recommendation, as last listed: `true` or `false`.",
        "comments": "GAO's comments on the agency's progress as last listed, untrimmed; NULL where it states none.",
        "topics": "The topic the export files it under, as last listed; NULL where it states none.",
        "first_seen": (
            "The date of the first export read that listed it: when this table first saw it open, not when GAO made it."
        ),
        "last_seen": "The date of the latest export read that listed it.",
        "listed_open": (
            "Whether the latest export read lists it: `false` once GAO no longer lists it as open, which is how a "
            "closed recommendation leaves the export."
        ),
        "status_as_of": (
            "The export's own status-as-of stamp, verbatim, from the latest export that listed it; GAO labels it EST "
            "year round, though it is Eastern local time."
        ),
    },
)


def gao_recommendation_id(report_id: str, agency: str, recommendation: str) -> str:
    """``sha256:`` over the lowercased publication number, the agency and the text, whitespace runs folded to one space.

    The fold keeps the key where GAO respaces a field: ``str.split`` also splits on the no-break spaces the export holds.
    Case is kept, since a changed word is a changed recommendation.
    """
    parts = (report_id.lower(), " ".join(agency.split()), " ".join(recommendation.split()))
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
            recommendation.report_id, recommendation.agency, recommendation.recommendation
        ),
        "report_id": text(recommendation.report_id),
        "publication_number": text(recommendation.publication_number),
        "publication_title": text(recommendation.publication_title),
        "publication_date": recommendation.publication_date.isoformat(),
        "director_name": text(recommendation.director_name),
        "agency": text(recommendation.agency),
        "recommendation": text(recommendation.recommendation),
        "status": text(recommendation.status),
        "priority": flag(recommendation.priority),
        "comments": text(recommendation.comments),
        "topics": text(recommendation.topics),
        "first_seen": seen,
        "last_seen": seen,
        "listed_open": flag(True),
        "status_as_of": text(status_as_of),
    }


__all__ = ["GAO_RECOMMENDATIONS", "gao_recommendation_id", "shape_gao_recommendation"]
