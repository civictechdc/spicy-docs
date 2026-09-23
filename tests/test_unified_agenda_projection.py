"""The one Unified Agenda field-path projection: RefSpec's rules, on publisher excerpts."""

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.sources.unified_agenda import UnifiedAgendaEdition
from spicy_docs.sources.unified_agenda.projection import (
    CONTINUATION_LABEL_FAMILIES,
    MANGLED_APOSTROPHE_EDITIONS,
    UnifiedAgendaAuthorityContinuation,
    UnifiedAgendaTimetableEntry,
    legal_authority_continuations,
    project_unified_agenda_edition,
)
from spicy_docs.sources.unified_agenda.records import UnifiedAgendaSourceError

FIXTURES = Path(__file__).parent / "fixtures" / "unified_agenda"


def project(body, stem="202510", **kwargs):
    rows = []
    scan = project_unified_agenda_edition(body, edition=UnifiedAgendaEdition(stem), on_record=rows.append, **kwargs)
    return scan, rows


def edition(*records, publication="202510"):
    return (
        "<REGINFO_RIN_DATA>"
        + "".join(
            f"<RIN_INFO><RIN>{rin}</RIN><PUBLICATION><PUBLICATION_ID>{publication}</PUBLICATION_ID></PUBLICATION>"
            f"{fields}</RIN_INFO>"
            for rin, fields in records
        )
        + "</REGINFO_RIN_DATA>"
    ).encode()


def test_retained_edition_projects_its_citation_paths_beside_the_raw_record():
    body = (FIXTURES / "reginfo-rin-data-202510.xml").read_bytes()
    scan, rows = project(body)
    assert (scan.input_sha256, scan.input_bytes) == (hashlib.sha256(body).hexdigest(), len(body))
    assert (scan.publication_id, scan.record_count, scan.repaired_bytes) == ("202510", 2, 0)
    first = rows[0]
    assert (first.rin, first.publication_id) == ("0503-AA90", "202510")
    assert first.legal_authorities == ("5 U.S.C. 301", "42 U.S.C. 2000bb et seq")
    assert first.timetable[0].date_text == "11/00/2026"  # a projected month keeps its zero day
    assert first.legal_authority_continuations == ()
    assert [field.element.tag for field in first.record.fields if field.element.tag == "ABSTRACT"] == ["ABSTRACT"]


def test_whitespace_runs_and_lone_non_ascii_spaces_collapse_to_one_space():
    # Verbatim values: 0694-AC24 and 1076-AD97 (200004), 0579-AA83 (199910), 1018-AS49 (199510),
    # 1545-BS24 and 1210-AC27 (202510, thin space), 1615-AC75 (202510, narrow no-break space).
    fields = (
        "<CFR_LIST><CFR>15 CFR  730, 732, 734, 736, 740,</CFR><CFR>25  CFR 70</CFR>"
        "<CFR>26 CFR §§\u20091.530A-2</CFR><CFR>29 CFR \u20092520.104b-1(c)</CFR>"
        "<CFR>\n   </CFR><CFR/></CFR_LIST>"
        "<LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY>7 USC 164  to 167</LEGAL_AUTHORITY>"
        "<LEGAL_AUTHORITY>8 U.S.C. 1185 note (sec. 7209 of\u202fPub. L. 108-458)</LEGAL_AUTHORITY>"
        "<LEGAL_AUTHORITY>\t49 USC 44701 to\n 44702 </LEGAL_AUTHORITY></LEGAL_AUTHORITY_LIST>"
        "<TIMETABLE_LIST><TIMETABLE><TTBL_ACTION>NPRM  (Reopening of Comment Period)</TTBL_ACTION>"
        "<TTBL_DATE>09/09/1993</TTBL_DATE><FR_CITATION>58 FR  47428</FR_CITATION></TIMETABLE>"
        "<TIMETABLE><TTBL_ACTION>Final Action</TTBL_ACTION><FR_CITATION> </FR_CITATION></TIMETABLE>"
        "</TIMETABLE_LIST>"
    )
    [row] = project(edition(("0694-AC24", fields)))[1]
    assert row.cfr_references == (
        "15 CFR 730, 732, 734, 736, 740,",
        "25 CFR 70",
        "26 CFR §§ 1.530A-2",
        "29 CFR 2520.104b-1(c)",
    )
    assert row.legal_authorities == (
        "7 USC 164 to 167",
        "8 U.S.C. 1185 note (sec. 7209 of Pub. L. 108-458)",
        "49 USC 44701 to 44702",
    )
    assert row.timetable == (
        UnifiedAgendaTimetableEntry("NPRM (Reopening of Comment Period)", "09/09/1993", "58 FR 47428"),
        # An absent TTBL_DATE (3,818 entries in the retained editions) and a blank citation are both None.
        UnifiedAgendaTimetableEntry("Final Action", None, None),
    )


def test_every_list_is_read_and_only_its_named_items():
    fields = (
        "<CFR_LIST><CFR>40 CFR 60</CFR><NOTE>not a citation</NOTE></CFR_LIST><CFR_LIST><CFR>40 CFR 63</CFR></CFR_LIST>"
        "<LEGAL_AUTHORITY_LIST/><LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY>42 USC 7401</LEGAL_AUTHORITY>"
        "</LEGAL_AUTHORITY_LIST>"
        "<TIMETABLE_LIST><TIMETABLE><TTBL_ACTION>NPRM</TTBL_ACTION><TTBL_ACTION>second</TTBL_ACTION></TIMETABLE>"
        "<OTHER><TTBL_ACTION>not an entry</TTBL_ACTION></OTHER></TIMETABLE_LIST>"
        "<TIMETABLE_LIST><TIMETABLE><TTBL_ACTION>Final Rule</TTBL_ACTION></TIMETABLE></TIMETABLE_LIST>"
    )
    [row] = project(edition(("2060-AA00", fields)))[1]
    assert row.cfr_references == ("40 CFR 60", "40 CFR 63")
    assert row.legal_authorities == ("42 USC 7401",)
    # A repeated child inside one entry is read at its first occurrence, as both prior readers did.
    assert [entry.action for entry in row.timetable] == ["NPRM", "Final Rule"]


def test_the_2004_control_byte_is_repaired_in_memory_for_its_two_editions_only():
    path = FIXTURES / "record-200404-1084-AA00.xml"
    body = path.read_bytes()
    assert MANGLED_APOSTROPHE_EDITIONS == ("200404", "200410")
    scan, [row] = project(body, "200404")
    provenance = json.loads((FIXTURES / "records-provenance.json").read_text())
    assert scan.input_sha256 == next(item for item in provenance if item["fixture"] == path.name)["fixture_sha256"]
    assert (scan.input_bytes, scan.repaired_bytes) == (len(body), 1)
    abstract = next(field for field in row.record.fields if field.element.tag == "ABSTRACT")
    assert "Department\u2019s" in abstract.text
    assert row.legal_authorities[:2] == ("30 USC 601 to 604", "30 USC 611")
    assert row.timetable[0] == UnifiedAgendaTimetableEntry("NPRM", "07/00/2004", None)
    # The served bytes are unchanged and still refused where no repair was measured.
    assert body.count(b"\x19") == 1
    relabeled = body.replace(b"<PUBLICATION_ID>200404<", b"<PUBLICATION_ID>202510<")
    with pytest.raises(UnifiedAgendaSourceError, match="malformed"):
        project(relabeled, "202510")


def test_the_repair_does_not_count_against_the_served_byte_bound():
    body = (FIXTURES / "record-200404-1084-AA00.xml").read_bytes()
    assert project(body, "200404", max_bytes=len(body))[0].repaired_bytes == 1
    with pytest.raises(UnifiedAgendaSourceError, match="max_bytes"):
        project(body, "200404", max_bytes=len(body) - 1)


def test_retained_continuation_is_read_whole_and_stops_at_the_paragraph_mark():
    # 1115-AE47, Spring 1997: CFR cites precede the mark; the authorities after it are one comma list that a
    # citation grammar reads whole and misreads if split first.
    _, [row] = project((FIXTURES / "record-199704-1115-AE47.xml").read_bytes(), "199704")
    assert row.legal_authorities[-1] == "..."  # the boxes say more follow
    [continuation] = row.legal_authority_continuations
    assert continuation.label_family == "additional-legal-authority"
    assert continuation.marker == "Additional Legal Authorities:"
    assert continuation.text.startswith("8 USC 1186b, 1187, 1201, 1203, 1221,")
    assert continuation.text.endswith("28 USC 509, 510, 1746; 31 USC 9701; 3 CFR, 1982 Comp., p. 166; 8 CFR part 2.")
    assert "8 CFR 232" not in continuation.text
    assert continuation.label_family in CONTINUATION_LABEL_FAMILIES


def continuation_texts(text):
    return [one.text for one in legal_authority_continuations(text)]


def test_a_continuation_stops_at_each_of_its_three_boundaries():
    # The paragraph mark: 3235-AG65, Fall 1995, verbatim.
    assert legal_authority_continuations(
        "LEGAL AUTHORITY CONT: 15 USC 77(g); 15 USC 77(j); 15 USC 77 (eee) ^PRFA:  N"
    ) == (
        UnifiedAgendaAuthorityContinuation(
            "legal-authority-cont", "LEGAL AUTHORITY CONT:", "15 USC 77(g); 15 USC 77(j); 15 USC 77 (eee)"
        ),
    )
    # The blank line: 3235-AH16, Spring 1999, verbatim, with another field's continuation behind it.
    assert continuation_texts(
        "LEGAL AUTHORITY CONT: 15 USC 78i; 15 USC 78o; 15 USC 78q; 15 USC 78w; 15 USC 78mm \n"
        "\nCFR CITATION CONT: 17 CFR 249.617 (Revision)"
    ) == ["15 USC 78i; 15 USC 78o; 15 USC 78q; 15 USC 78w; 15 USC 78mm"]
    # Another field's label, which no retained edition needs: the same two fields joined by a semicolon.
    assert continuation_texts("LEGAL AUTHORITY CONT: 15 USC 78i; 15 USC 78mm; CFR CITATION CONT: 17 CFR 249.617") == [
        "15 USC 78i; 15 USC 78mm;"
    ]
    # "continued" in prose is not a label, because a label ends in a colon.
    assert continuation_texts("LEGAL AUTHORITY CONT: 29 USC 1027, as continued by Pub. L. 104-191") == [
        "29 USC 1027, as continued by Pub. L. 104-191"
    ]


@pytest.mark.parametrize(
    ("text", "family", "marker"),
    [
        ("LEGAL AUTHORITIES CONT: 42 USC 1395", "legal-authority-cont", "LEGAL AUTHORITIES CONT:"),
        ("Legal Authority Continue......... 42 USC 1395", "legal-authority-cont", "Legal Authority Continue........."),
        ("Legal Authority (Continued) 42 USC 1395", "legal-authority-cont", "Legal Authority (Continued)"),
        ("Additional Legal Authorities 42 USC 1395", "additional-legal-authority", "Additional Legal Authorities"),
        (
            "Additional legal authority information: 42 USC 1395",
            "additional-legal-authority",
            "Additional legal authority information:",
        ),
        (
            "Continue from #8 Legal Authority........... 42 USC 1395",
            "additional-legal-authority",
            "Continue from #8 Legal Authority...........",
        ),
    ],
)
def test_each_measured_label_spelling_names_its_family(text, family, marker):
    assert legal_authority_continuations(text) == (UnifiedAgendaAuthorityContinuation(family, marker, "42 USC 1395"),)


def test_labels_that_do_not_continue_the_authority_list_are_not_read():
    # A label may follow anything (0938-AG59 puts a docket number first) and is read from its end.
    assert continuation_texts("HSQ-215 ^PLEGAL AUTHORITY CONT: 42 USC 1395f(b) 42 USC 1395l 42 USC 1395ww") == [
        "42 USC 1395f(b) 42 USC 1395l 42 USC 1395ww"
    ]
    for text in (
        "LEGAL AUTHORITY CONT: ^PRFA: N",  # a label with nothing behind it
        "",
        "STATUTORY DEADLINE CONT: 07/01/1997",  # other fields' continuations
        "CFR CITATIONS CONT: 8 CFR 232, 233",
        "Legal Authority: PL-105-33, sec 4505",  # restating the field is not continuing it (0938-AI52, 199804)
        "8. Legal Authority: OMB Circular A-110",  # 1090-AA67, 199804
        "Additional authority DOT Order 5660.1A",  # 2125-AD78: never says "legal"
    ):
        assert legal_authority_continuations(text) == (), text


def test_continuations_read_every_additional_info_with_its_whitespace_intact():
    fields = (
        "<ADDITIONAL_INFO>LEGAL AUTHORITY CONT: 42 USC\n  1395\n\nRFA: N</ADDITIONAL_INFO>"
        "<ADDITIONAL_INFO>Additional Legal Authority: 5 USC 301</ADDITIONAL_INFO>"
    )
    [row] = project(edition(("0938-AG59", fields)))[1]
    assert [(one.label_family, one.text) for one in row.legal_authority_continuations] == [
        ("legal-authority-cont", "42 USC 1395"),
        ("additional-legal-authority", "5 USC 301"),
    ]


@pytest.mark.parametrize(
    ("body", "stem", "message"),
    [
        (edition(("0503-AA90", "")), "202504", "another edition"),
        (edition(("0503-AA90", ""), ("0503-AA90", "")), "202510", "repeats a RIN"),
        (b"<REGINFO_RIN_DATA><RIN_INFO><CFR_LIST/></RIN_INFO></REGINFO_RIN_DATA>", "202510", "exactly one RIN"),
        (b"<REGINFO_RIN_DATA/>", "202510", "no RIN_INFO"),
    ],
)
def test_projection_proves_identity_as_acquisition_does(body, stem, message):
    with pytest.raises(UnifiedAgendaSourceError, match=message):
        project(body, stem)


def test_legacy_file_stem_projects_the_edition_its_records_state():
    scan, [row] = project(edition(("0503-AA90", ""), publication="201210"), "2012")
    assert scan.publication_id == row.publication_id == "201210"


def test_invalid_arguments_and_callback_failures_refuse():
    body = edition(("0503-AA90", ""))
    with pytest.raises(UnifiedAgendaSourceError, match="UnifiedAgendaEdition"):
        project_unified_agenda_edition(body, edition="202510", on_record=list.append)
    with pytest.raises(UnifiedAgendaSourceError, match="callable"):
        project_unified_agenda_edition(body, edition=UnifiedAgendaEdition("202510"), on_record=None)
    with pytest.raises(UnifiedAgendaSourceError, match="max_bytes"):
        project(body.decode())
    failure = RuntimeError("receiver refused")

    def refuse(_row):
        raise failure

    with pytest.raises(RuntimeError) as raised:
        project_unified_agenda_edition(body, edition=UnifiedAgendaEdition("202510"), on_record=refuse)
    assert raised.value is failure
