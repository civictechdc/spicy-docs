"""FERC's own docket-prefix and document class/type vocabularies, pinned with their publication identity.

Both rosters are FERC's published, agency-specific controlled lists, read from
the exact PDF bytes RefSpec pins (see RefSpec's ``refspec.registry.ferc_elibrary_codes``,
which owns the parsers and the acquisition pipeline). This module keeps the
parsed values and the provenance needed to validate FERC eLibrary identities;
it imports nothing from the rest of this package, so the readers can import it
without a cycle.

Pins (publication URL, SHA-256, byte length, row count):

* Docket prefixes -- ``https://elibrary.ferc.gov/eLibrary/assets/docket-prefix.pdf``
  (the "Docket Prefix List", dated June 2025), ``sha256:c32efae9f51a70b6f955821d2fb3d3025995ef0e17e57bf2d32dfa16c2508dcb``,
  282,729 bytes, 95 rows: the complete active and discontinued prefix scheme.
  Every active prefix is two uppercase letters except the one-letter ``P``
  (hydropower projects); three discontinued hyphenated spellings (``E-``,
  ``G-``, ``R-``) are pre-1960/1974 forms the docket grammar does not express.
* Document class/type -- ``https://www.ferc.gov/sites/default/files/2025-06/Document%20Class%20Types%20January%202025.pdf``
  (the "Document Class and Type" tables, January 2025), ``sha256:af632c9c6adbf0e7919d17e018b3a65078d0746bd1ab69a8d9fa65043720d688``,
  193,934 bytes, 235 rows. Four (class, type) pairs repeat across the PDF's
  Category/Library columns, so the 235 rows collapse to the 230 unique
  ``(classification, type description)`` pairs pinned here; the search route
  selects by that pair, not by a row's Category or Library.

Captured 2026-08-03 into RefSpec's digest-pinned source store (the same bytes
this module's pins verify); re-parsed here 2026-09-24 with RefSpec's parser.
Values are the publisher's own spellings, including their odd ones (``ERO
Certification or performance assessment``), and are never corrected.

Membership in these rosters is evidence, not a gate: the readers refuse only
shapes that cannot be a publisher value (see the identity grammars in
``elibrary.py``) and pass unknown-but-plausible values through to the
publisher, whose answer is the record.
"""

from __future__ import annotations

import re
from typing import Final

FERC_PUBLISHER: Final = "Federal Energy Regulatory Commission"
FERC_DOCKET_PREFIX_PDF_URL: Final = "https://elibrary.ferc.gov/eLibrary/assets/docket-prefix.pdf"
FERC_DOCKET_PREFIX_PDF_SHA256: Final = "sha256:c32efae9f51a70b6f955821d2fb3d3025995ef0e17e57bf2d32dfa16c2508dcb"
FERC_DOCKET_PREFIX_PDF_BYTE_LENGTH: Final = 282_729
FERC_DOCKET_PREFIX_ROW_COUNT: Final = 95
FERC_CLASS_TYPE_PDF_URL: Final = (
    "https://www.ferc.gov/sites/default/files/2025-06/Document%20Class%20Types%20January%202025.pdf"
)
FERC_CLASS_TYPE_PDF_SHA256: Final = "sha256:af632c9c6adbf0e7919d17e018b3a65078d0746bd1ab69a8d9fa65043720d688"
FERC_CLASS_TYPE_PDF_BYTE_LENGTH: Final = 193_934
FERC_CLASS_TYPE_PDF_ROW_COUNT: Final = 235
FERC_CLASS_TYPE_PAIR_COUNT: Final = 230
#: The PDFs entered RefSpec's digest-pinned source store on this day; the
#: publisher prints no revision date on either document beyond its month.
FERC_SOURCE_CAPTURED: Final = "2026-08-03"

type DocketPrefixStatus = str

#: Every docket prefix FERC published in June 2025: (prefix, status), where
#: status is ``active`` or ``discontinued``. Discontinued prefixes remain
#: published docket spellings (older dockets keep them), so membership is
#: validated on the prefix alone and status is retained as the publisher's own
#: annotation.
DOCKET_PREFIXES: Final[tuple[tuple[str, DocketPrefixStatus], ...]] = (
    ("AC", "active"),
    ("AD", "active"),
    ("AI", "active"),
    ("CD", "active"),
    ("CE", "active"),
    ("CP", "active"),
    ("CX", "active"),
    ("DI", "active"),
    ("DO", "active"),
    ("DR", "active"),
    ("DV", "active"),
    ("EC", "active"),
    ("EF", "active"),
    ("EG", "active"),
    ("EL", "active"),
    ("EM", "active"),
    ("EP", "active"),
    ("ER", "active"),
    ("ES", "active"),
    ("ET", "active"),
    ("EX", "active"),
    ("EY", "active"),
    ("FA", "active"),
    ("FC", "active"),
    ("GP", "active"),
    ("GT", "active"),
    ("GX", "active"),
    ("HC", "active"),
    ("IN", "active"),
    ("IS", "active"),
    ("JR", "active"),
    ("LA", "active"),
    ("LP", "active"),
    ("MC", "active"),
    ("MD", "active"),
    ("MG", "active"),
    ("ML", "active"),
    ("MO", "active"),
    ("MT", "active"),
    ("NJ", "active"),
    ("NL", "active"),
    ("NP", "active"),
    ("NR", "active"),
    ("OA", "active"),
    ("OR", "active"),
    ("OT", "active"),
    ("PA", "active"),
    ("PF", "active"),
    ("PH", "active"),
    ("PL", "active"),
    ("PR", "active"),
    ("PT", "active"),
    ("QF", "active"),
    ("QM", "active"),
    ("RA", "active"),
    ("RC", "active"),
    ("RD", "active"),
    ("RM", "active"),
    ("RO", "active"),
    ("RP", "active"),
    ("RR", "active"),
    ("RS", "active"),
    ("RT", "active"),
    ("SA", "active"),
    ("SC", "active"),
    ("TC", "active"),
    ("TF", "active"),
    ("TM", "active"),
    ("TQ", "active"),
    ("TS", "active"),
    ("TX", "active"),
    ("UL", "active"),
    ("ZZ", "active"),
    ("HB", "active"),
    ("IC", "active"),
    ("ID", "active"),
    ("P", "active"),
    ("AR", "discontinued"),
    ("CI", "discontinued"),
    ("CS", "discontinued"),
    ("DA", "discontinued"),
    ("E-", "discontinued"),
    ("FS", "discontinued"),
    ("G-", "discontinued"),
    ("IR", "discontinued"),
    ("IT", "discontinued"),
    ("JD", "discontinued"),
    ("PD", "discontinued"),
    ("PV", "discontinued"),
    ("R-", "discontinued"),
    ("RE", "discontinued"),
    ("RI", "discontinued"),
    ("SP", "discontinued"),
    ("ST", "discontinued"),
    ("TA", "discontinued"),
)

#: The 230 unique ``(classification, type description)`` pairs the January 2025
#: PDF publishes, in the PDF's own row order with repeated pairs collapsed.
#: These are exactly the ``documentClass``/``documentType`` pairs the search
#: route accepts; a pair absent from this roster is passed through to the
#: publisher, whose answer is the evidence.
CLASS_TYPE_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("ALJ Issuance", "ALJ Initial Decision/Certification of Initial Decision and Record"),
    ("ALJ Issuance", "ALJ Notice"),
    ("ALJ Issuance", "Certification of Question and Memorandum to the Commission"),
    ("ALJ Issuance", "Certification of Record"),
    ("ALJ Issuance", "Certification of Settlement"),
    ("ALJ Issuance", "Discovery Order"),
    ("ALJ Issuance", "Findings of Fact"),
    ("ALJ Issuance", "Order Permitting Interlocutory Appeal"),
    ("ALJ Issuance", "Order on Transcript Correction"),
    ("ALJ Issuance", "Procedural Order/Procedural Report"),
    ("ALJ Issuance", "Protective Order"),
    ("ALJ Issuance", "Report to the Commission"),
    ("Affirmation", "Affidavits/Sworn Statement"),
    ("Affirmation", "Affirmation to Testimony"),
    ("Affirmation", "Certificate of Service"),
    ("Agreement/Understanding/Contract", "Contract/Letter Agreement"),
    ("Agreement/Understanding/Contract", "Memoranda of Understanding(MOU)/Memoranda of Agreement (MOA)"),
    ("Agreement/Understanding/Contract", "Settlement Agreement (Stipulation and Agreement)"),
    ("Agreement/Understanding/Contract", "Stipulation"),
    ("Applicant Correspondence", "Correspondence Concerning Filing Fees and Annual Charges"),
    ("Applicant Correspondence", "Deficiency Letter/Data Response"),
    ("Applicant Correspondence", "General Correspondence"),
    ("Applicant Correspondence", "Request for Delay of Action/Extension of Time"),
    ("Applicant Correspondence", "Response to Inquiry"),
    ("Applicant Correspondence", "Supplemental/Additional Information"),
    ("Applicant Correspondence", "Withdrawal of Application"),
    ("Application/Petition/Request", "Abandonment of Service or Facility"),
    ("Application/Petition/Request", "Allegation of Non-Compliance"),
    ("Application/Petition/Request", "Application For Transmission Line License"),
    ("Application/Petition/Request", "Application To Amend License or Exemption"),
    ("Application/Petition/Request", "Application for Change in Land & Water Rights"),
    ("Application/Petition/Request", "Application for Participation in Pilot Program"),
    ("Application/Petition/Request", "Application for Preliminary Permit"),
    ("Application/Petition/Request", "Application for Presidential Permit for Pipeline Facilities"),
    ("Application/Petition/Request", "Approval of Interlocking Position"),
    ("Application/Petition/Request", "Certificate of Public Convenience and Necessity"),
    ("Application/Petition/Request", "Certification of Generation for Tax Credit"),
    ("Application/Petition/Request", "Complaints"),
    ("Application/Petition/Request", "Compliance Electric Rate Filing"),
    ("Application/Petition/Request", "Compliance Electric Refund Report"),
    ("Application/Petition/Request", "Comprehensive Plan Section 10(a)(2)(A)"),
    ("Application/Petition/Request", "Declaration of Intent"),
    ("Application/Petition/Request", "Determination of Jurisdiction"),
    ("Application/Petition/Request", "Disposition of Facilities Filing"),
    ("Application/Petition/Request", "ERO Certification or performance assessment"),
    ("Application/Petition/Request", "ERO Funding"),
    ("Application/Petition/Request", "Electric Rate Filing"),
    ("Application/Petition/Request", "Electric Transmission Service"),
    ("Application/Petition/Request", "Exempt Wholesale Generator Request"),
    ("Application/Petition/Request", "Exemption From License - Conduit/5MW"),
    ("Application/Petition/Request", "Federal Rate Filing"),
    ("Application/Petition/Request", "Financial Audit Refund Report"),
    ("Application/Petition/Request", "Foreign Utility Company Request"),
    ("Application/Petition/Request", "Gas and Oil Tariff Filing"),
    ("Application/Petition/Request", "License/Relicense Application"),
    ("Application/Petition/Request", "Merger Filing"),
    ("Application/Petition/Request", "Petition for Declaratory Order"),
    ("Application/Petition/Request", "Qualifying Facility Application or PURPA Energy Utility Filing"),
    ("Application/Petition/Request", "Regional Advisory Body"),
    ("Application/Petition/Request", "Regional Entities"),
    ("Application/Petition/Request", "Reliability Std. -approval, remand, or modification"),
    ("Application/Petition/Request", "Reliability Std. -violation, disposition, or penalty"),
    ("Application/Petition/Request", "Request for Interpretation"),
    ("Application/Petition/Request", "Rule Change - ERO or Regional Entity"),
    ("Application/Petition/Request", "Securities Issuances"),
    ("Application/Petition/Request", "Standards of Conduct"),
    ("Application/Petition/Request", "Standards of Conduct of Public Utility"),
    ("Application/Petition/Request", "Surrender"),
    ("Application/Petition/Request", "Tariff Filing"),
    ("Application/Petition/Request", "Transfer of Hydropower License or Exemption"),
    ("Application/Petition/Request", "Utility Accounting Request"),
    ("Application/Petition/Request", "Waiver Request For Hydro Regulation or Terms/Conditions"),
    ("Application/Petition/Request", "Waiver Request for Hydro Fees and Charges"),
    ("Application/Petition/Request", "Waiver of Electric Regulation"),
    ("Application/Petition/Request", "Waiver of Filing Fee"),
    ("Application/Petition/Request", "Waiver of Oil or Gas Regulation"),
    ("Approved Designation", "Approved Designation"),
    ("Briefing/Arguments of Law", "Brief"),
    ("Briefing/Arguments of Law", "Findings of Fact/Conclusions of Law"),
    ("Briefing/Arguments of Law", "Statement of Issues or Position"),
    ("Comments/Protest", "Comment on Filing"),
    ("Comments/Protest", "Litigation Comment"),
    ("Comments/Protest", "Rulemaking Comment"),
    ("Comments/Protest", "Settlement Comment"),
    ("Court Related Documents", "Court Related Documents"),
    ("Deposition Document", "Deposition"),
    ("Deposition Document", "Notice/Motion to Depose"),
    ("Deposition Document", "Objection to Deposition"),
    ("Drawing/Maps", "Drawing/Maps"),
    ("Exhibit", "Exhibit"),
    ("FERC Comment", "Comment on Pending Legislation"),
    ("FERC Comment", "Comment on Policies/Procedures Before Government Agencies"),
    ("FERC Correspondence With Applicant", "Compliance Directives"),
    ("FERC Correspondence With Applicant", "Deficiency Letter"),
    ("FERC Correspondence With Applicant", "General Correspondence"),
    ("FERC Correspondence With Applicant", "Request for Additional Information"),
    ("FERC Correspondence With Government Agencies", "FERC Correspondence With Government Agencies"),
    ("FERC Correspondence with Tribal Governments", "FERC Correspondence with Tribal Governments"),
    ("FERC Memo", "Internal Transmittal Memo"),
    ("FERC Memo", "Memo to Commission"),
    ("FERC Memo", "Non-Compliance Memo"),
    ("FERC Memo", "Other Internal Memo"),
    ("FERC Memo", "Telephone Conversation or Electronic Mail Memo"),
    ("FERC Report/Study", "Audit Summary"),
    ("FERC Report/Study", "Compliance Audit Summary"),
    ("FERC Report/Study", "Construction Inspection Report"),
    ("FERC Report/Study", "Dam Safety Inspection Report/Operation Report"),
    ("FERC Report/Study", "EPUI and Public Safety Report"),
    ("FERC Report/Study", "Environmental Assessment (EA) and Environmental Impact Statement (EIS)"),
    ("FERC Report/Study", "Environmental Report"),
    ("FERC Report/Study", "Other FERC Report/Study"),
    ("FERC Report/Study", "Policy Study"),
    ("FERC Report/Study", "Pre-license or Pre-Exemption Inspection Report"),
    ("FERC Report/Study", "Safety and Design Assessment"),
    ("FERC Report/Study", "Scoping Document"),
    ("FERC Report/Study", "Special Inspection Report"),
    ("Informational Correspondence", "Agenda Materials"),
    ("Informational Correspondence", "Informational Correspondence (Miscellaneous Issuances)"),
    ("Informational Correspondence", "News Release"),
    ("Interrogatory/Data Request", "Data Request Document"),
    ("Interrogatory/Data Request", "Response to Data Request"),
    ("Intervention", "Motion to Intervene Out of Time"),
    ("Intervention", "Motion/Notice of Intervention"),
    ("Intervention", "Withdrawal of Intervention"),
    ("Litigation Correspondence", "Litigation Correspondence"),
    ("Notice", "Formal Notice"),
    ("Notice", "Notice of Proposed Rulemaking"),
    ("Order/Opinion", "Commission Order/Opinion"),
    ("Order/Opinion", "Delegated Order"),
    ("Order/Opinion", "Dissent/Concurrence by the Commissioner"),
    ("Order/Opinion", "Interpretation and Advisory Opinion"),
    ("Other Submittal", "Congressional Submittal"),
    ("Other Submittal", "Government Agency Submittal"),
    ("Other Submittal", "Other External Submittal"),
    ("Other Submittal", "Tribal Government Submittal"),
    ("Pleading/Motion", "Answer/Response to a Pleading/Motion"),
    ("Pleading/Motion", "Election"),
    ("Pleading/Motion", "Motion to Compel Production"),
    ("Pleading/Motion", "Objection to Motion to Compel Production"),
    ("Pleading/Motion", "Petition for Review"),
    ("Pleading/Motion", "Procedural Motion"),
    ("Pleading/Motion", "Production of Document"),
    ("Pleading/Motion", "Request for Hearing"),
    ("Pleading/Motion", "Request for Rehearing or Appeal"),
    ("Pleading/Motion", "Response to Complaint"),
    ("Report/Form", "157.207 Annual Construction Report"),
    ("Report/Form", "2.55 Annual Construction Report"),
    ("Report/Form", "260.9 Service Interruption Report"),
    ("Report/Form", "284.11 Annual Construction Report"),
    ("Report/Form", "284.126 (g) Semi-Annual Storage Report"),
    ("Report/Form", "284.288 Annual Pipeline Sales Report"),
    ("Report/Form", "Accident Report"),
    ("Report/Form", "Annual Charges Report"),
    ("Report/Form", "Annual Conveyance Report"),
    ("Report/Form", "Annual Generation Report"),
    ("Report/Form", "Annual Headwater Benefits Compliance"),
    ("Report/Form", "Annual Spill Gate Testing Report"),
    ("Report/Form", "Annual Water Quality/Minimum Flow"),
    ("Report/Form", "CPA Statement Certifications"),
    ("Report/Form", "California PX/ISO Monthly Reports"),
    ("Report/Form", "Certificate of Compliance Report"),
    ("Report/Form", "Cultural Resources Inventory - Report/Archaeological Study"),
    ("Report/Form", "Dam Safety Compliance Report"),
    ("Report/Form", "Discount Rate Report"),
    ("Report/Form", "EAP Testing Report"),
    ("Report/Form", "ERO Reliability or Adequacy assess. or requested info."),
    ("Report/Form", "Electric Quarterly Report"),
    ("Report/Form", "Emergency Action Plan"),
    ("Report/Form", "Emergency Gas Report"),
    ("Report/Form", "Environmental Study & Report"),
    ("Report/Form", "Environmental and Recreational Compliance Report"),
    ("Report/Form", "FERC Form 719 Public Utility Sellers Report"),
    ("Report/Form", "FERC-61 - Narrative Description of Service Company Functions"),
    ("Report/Form", "FERC-730 - Report of Transaction Investment Activity"),
    ("Report/Form", "Fee Collection or Validation Forms"),
    ("Report/Form", "Form 1 - Annual Rpt. for Major Electric Utilities, Licensees & Others"),
    ("Report/Form", "Form 1-F - Annual Report for Non-Major Public Utilities"),
    ("Report/Form", "Form 11 - Natural Gas Pipeline Company Qtrly. Stmt. of Monthly"),
    ("Report/Form", "Form 14 - Annual Report for Importers and Exporters of Natural Gas"),
    ("Report/Form", "Form 2 - Annual Report of Major Natural Gas Companies"),
    ("Report/Form", "Form 2-A - Annual Report of Non-Major Natural Gas Companies"),
    ("Report/Form", "Form 3-Q -Quarterly financial report of electric utilities- licensees- and natural gas companies"),
    ("Report/Form", "Form 423 - Monthly Rpt. of Cost & Quality of Fuels for Electric Plants"),
    ("Report/Form", "Form 542 - Purchased Gas Adjustment"),
    ("Report/Form", "Form 549D-Quarterly Transportation & Storage Report for Intrastate Natural Gas and Hinshaw Pipe"),
    ("Report/Form", "Form 552 - Annual Report of Natural Gas Transactions"),
    ("Report/Form", "Form 561 - Annual Report of Interlocking Positions"),
    ("Report/Form", "Form 566 - Report of Utilitys 20 Largest Purchasers"),
    ("Report/Form", "Form 567 - Annual Report of System Flow Diagrams and Capacity"),
    ("Report/Form", "Form 580 - Fuel and Energy Purchase Practices"),
    ("Report/Form", "Form 6 - Annual Report of Oil Pipeline Companies"),
    ("Report/Form", "Form 6-Q -Quarterly report of oil pipeline companies"),
    ("Report/Form", 'Form 60 - Annual Report by "Centralized" Service Company'),
    ("Report/Form", "Form 714 - Annual Electric Control and Planning Area Report"),
    ("Report/Form", "Form 715 - Annual Transmission Planning and Evaluation Report"),
    ("Report/Form", "Form 8 - Underground Gas Storage Report"),
    ("Report/Form", "Form 80 - Licensed Hydropower Development Recreation Report"),
    ("Report/Form", "Gas Refund Report"),
    ("Report/Form", "ILP Comments or Study Request"),
    ("Report/Form", "ILP Initial or Updated Study Report"),
    ("Report/Form", "ILP Notice of Request for Formal Dispute Resolution"),
    ("Report/Form", "ILP Preliminary Licensing Proposal"),
    ("Report/Form", "ILP Proposed Study Plan or Revised Study Plan"),
    ("Report/Form", "Index of Customer"),
    ("Report/Form", "Notice/Report of Intent to Proceed with Emergency Procedures"),
    ("Report/Form", "OCSLA (Outer Continental Shelf Lands Act) Reports"),
    ("Report/Form", "Other Dam Safety Report"),
    ("Report/Form", "Other Utility Report"),
    ("Report/Form", "Part 12 Consultant Safety Inspection Reports"),
    ("Report/Form", "Peak Day Capacity Report"),
    ("Report/Form", "Power Marketer Quarterly Reports"),
    ("Report/Form", "Pre-Application Document"),
    ("Report/Form", "Pre-Filing Process"),
    ("Report/Form", "Pre-Filing Process Progress Report"),
    ("Report/Form", "Preliminary Permit Progress Report"),
    ("Report/Form", "Progress Report"),
    ("Report/Form", "Project Operations Compliance Report"),
    ("Report/Form", "Project Safety Compliance Report"),
    ("Report/Form", "Report of Refund Obligation"),
    ("Report/Form", "Securities Transaction Report"),
    ("Report/Form", "Transportation Report"),
    ("Status Report", "Status Report"),
    ("Subpoena", "Subpoena"),
    ("Testimony", "Initial Testimony"),
    ("Testimony", "Response (Rebuttal) Testimony"),
    ("Top Sheet", "Top Sheet"),
    ("Transcript", "Approved Transcript Correction"),
    ("Transcript", "Commission Open Meeting Transcript"),
    ("Transcript", "Conference/Meeting Transcript"),
    ("Transcript", "Hearing Transcript"),
)

#: The one-letter prefixes the roster carries are the active ``P`` and the
#: discontinued hyphenated forms; everything else is exactly two letters.
_DOCKET_PREFIX_SHAPE = re.compile(r"[A-Z]{2}|P")

_DOCKET_PREFIX_ROSTER: Final = dict(DOCKET_PREFIXES)

#: Roster prefixes whose dockets spell a hyphen and a serial number where others carry a
#: fiscal year: ``P-14683-000`` (hydropower projects) and ``ID-10800-000`` (interlocking
#: directorates; three ``ID-`` dockets in the live 2026-09-25 new-docket answer, receipt
#: ``ferc-elibrary-2026-09-25/new-dockets-rbfilingdate-2026-09-20-2026-09-25.json``). The
#: roster states no spelling, so a newly observed one is added here with its evidence.
SERIAL_DOCKET_PREFIXES: Final = ("ID", "P")
_CLASS_TYPE_PAIRS: Final = frozenset(CLASS_TYPE_PAIRS)


class FercVocabularyError(ValueError):
    """A value contradicts FERC's pinned eLibrary vocabularies."""


def docket_prefix_code(docket: str) -> str:
    """The docket's prefix, per the publisher's own prefix scheme (two letters, or ``P``).

    Raises :class:`FercVocabularyError` for a docket whose prefix is not a
    published prefix shape; the readers' own docket grammar is the gate, and
    this is the lookup that cites the roster.
    """
    value = docket.strip().upper()
    match = _DOCKET_PREFIX_SHAPE.match(value)
    if match is None:
        raise FercVocabularyError(f"{docket!r} does not start with a FERC docket prefix shape")
    return match[0]


def docket_prefix_status(prefix: str) -> DocketPrefixStatus | None:
    """The publisher's status for one prefix (``active``/``discontinued``), or ``None`` if unpublished."""
    return _DOCKET_PREFIX_ROSTER.get(prefix.strip().upper())


def is_documented_class_type(class_label: str, type_label: str) -> bool:
    """Whether the (class, type) pair is one of the 230 pairs FERC published in January 2025."""
    return (class_label, type_label) in _CLASS_TYPE_PAIRS


def require_documented_class_type(class_label: str, type_label: str) -> None:
    """Refuse a (class, type) pair this package itself asserts, if the pinned roster does not carry it.

    This is for constants the readers ship (``RULEMAKING_COMMENT``): a drift
    between the constant and the publisher's published vocabulary must fail at
    import, not surface as a zero-hit walk. Caller-supplied pairs are not
    checked here; they pass through to the publisher with its answer as the
    evidence.
    """
    if not is_documented_class_type(class_label, type_label):
        raise FercVocabularyError(
            f"({class_label!r}, {type_label!r}) is not a documented FERC eLibrary class/type pair"
        )


__all__ = [
    "CLASS_TYPE_PAIRS",
    "DOCKET_PREFIXES",
    "FERC_CLASS_TYPE_PAIR_COUNT",
    "FERC_CLASS_TYPE_PDF_BYTE_LENGTH",
    "FERC_CLASS_TYPE_PDF_ROW_COUNT",
    "FERC_CLASS_TYPE_PDF_SHA256",
    "FERC_CLASS_TYPE_PDF_URL",
    "FERC_DOCKET_PREFIX_PDF_BYTE_LENGTH",
    "FERC_DOCKET_PREFIX_PDF_SHA256",
    "FERC_DOCKET_PREFIX_PDF_URL",
    "FERC_DOCKET_PREFIX_ROW_COUNT",
    "FERC_PUBLISHER",
    "FERC_SOURCE_CAPTURED",
    "SERIAL_DOCKET_PREFIXES",
    "FercVocabularyError",
    "docket_prefix_code",
    "docket_prefix_status",
    "is_documented_class_type",
    "require_documented_class_type",
]
