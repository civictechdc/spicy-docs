"""One pass over one bill: thirteen tables, in an order where nothing reads another's output.

The family builder is the one place a bill's documents and this package's
findings meet; it lives here rather than in ``schemas/`` because composing
them needs ``sources.congress`` and ``interpretation``, which ``schemas/``
must not import. Model calls are injected at this boundary (``None`` skips
that model table, as a keyless CI run does) and never chosen here; the diff
runs on consecutive pairs only, the one superlinear step, and every other step
is linear in the rows produced with no re-parsing. Refusals are never silent:
a pair that cannot be diffed, a row with a null identity part, a version the
summarizer declined or the model's own reader refused each becomes a named
:class:`FamilyRefusal` and none aborts the rest of the bill.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from importlib import metadata
from json import JSONDecodeError, loads
from typing import Any, Protocol
from urllib.parse import urlsplit

from spicy_docs.interpretation import bill_stage, money_bills, version_kind
from spicy_docs.interpretation.bill_summaries import BillVersionText, DiffItemText, frame_for_kind
from spicy_docs.interpretation.model_call import ModelCallError
from spicy_docs.interpretation.section_classification import (
    CLASSIFICATION_LABELS,
    ClassifiableSection,
)
from spicy_docs.schemas.bill_diff_tables import (
    FINANCIAL_CHANGES,
    SECTION_DIFF_ITEMS,
    SECTION_DIFFS,
    TEXT_DIFF_CAP_BYTES,
    shape_financial_change,
    shape_section_diff,
    shape_section_diff_item,
)
from spicy_docs.schemas.bill_model_tables import (
    BILL_SUMMARIES,
    DIFF_SUMMARIES,
    SECTION_CLASSIFICATIONS,
    shape_bill_summary,
    shape_diff_summary,
    shape_section_classification,
)
from spicy_docs.schemas.bill_tables import (
    BILL_ACTIONS,
    BILL_COMMITTEES,
    BILL_PUBLISHER_SUMMARIES,
    CONGRESS_BILLS,
    latest_action_index,
    shape_bill,
    shape_bill_action,
    shape_bill_committee,
    shape_bill_publisher_summary,
)
from spicy_docs.schemas.bill_version_tables import (
    BILL_SECTIONS,
    BILL_VERSIONS,
    shape_bill_section,
    shape_bill_version,
)
from spicy_docs.schemas.cost_estimate_tables import (
    CBO_COST_ESTIMATES,
    PUBLICATION_ID_RULE,
    fold_cbo_cost_estimates,
    publication_id,
    shape_cbo_cost_estimate,
)
from spicy_docs.schemas.tables import Row, TableContract, TableContractError, bill_id, joined
from spicy_docs.sources.congress.bill_versions import (
    VersionCodeError,
    consecutive_pairs,
    printing_order,
    printing_version_code,
    version_slug,
    version_slug_reprints,
)
from spicy_docs.sources.congress.bill_versions import format_name as format_name_of
from spicy_docs.transport.credentials import scrub_credential

#: Which version kinds are worth a model call.
#:
#: The design said ``kind == "full_text"``.  Two things in the record types
#: widen it.  ``kind_uncertain``'s own label is "Full bill text (short --
#: verify)": it is a full-text slug whose document is thin, not a different
#: kind of document.  And BillTrax's own production guard is the complement --
#: its summarize route refuses a pair only when either side is
#: ``procedural_amendments`` or ``procedural_summary``, because summarizing
#: edit instructions as if they were bill text is the failure that matters.
#: ``unknown`` stays out: nothing has established that document carries text.
MODELLED_KINDS = frozenset({"full_text", "kind_uncertain"})


class BillFamilyError(ValueError):
    """The family cannot be built from the capture as it was given."""


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class EngineStamp:
    """Which diff engine, at which pinned commit, produced a ``section_diffs`` row.

    The stamp stands in for a matching-rule name because the rules are
    upstream's: a reader reproduces a row by installing this revision.
    """

    name: str
    version: str
    revision: str


@dataclass(frozen=True, slots=True)
class FamilyRefusal:
    """One row the family could have produced and did not, and why.

    A refusal is a record, not a log line: the rollup writes these beside the
    rows so a missing diff or a declined summary is countable.
    """

    table: str
    identity: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class BillVersionCapture:
    """One acquired printing of a bill: what was fetched, and what reading it produced.

    ``version_code`` is the sealed slug and ``source`` names the acquisition
    path (``govinfo``, ``congress``, ``govinfo-pdf``, ``upload``); any of the
    optional records may be absent, and each absence shows up as NULLs in the
    version row rather than as a dropped version. ``chosen_format`` is the
    offered link the body was actually fetched from and is never guessed here,
    because picking the preferred format would report ``xml`` for a row whose
    body is a PDF.
    """

    version: Any
    version_code: str
    source: str
    package_id: str | None = None
    #: The offered link the body was actually fetched from, which only the
    #: caller that fetched it knows.  It is never guessed here: picking the
    #: version's preferred format would report ``xml`` for a row whose body is
    #: a PDF, which is precisely the claim the capture columns exist to make
    #: checkable.  Absent, ``format_name`` and ``format_type`` are NULL.
    chosen_format: Any = None
    body: Any = None
    document: Any = None
    cleanup: Any = None
    #: For a PDF twin, the XML row it stands in for.  Both halves are needed:
    #: a version code is not unique across acquisition paths, which is the
    #: whole reason ``bill_versions`` keys on ``source`` too, and ``pair_type``
    #: resolves a twin by comparing the full key.
    equivalent_xml_version_code: str | None = None
    equivalent_xml_source: str | None = None

    @property
    def reference_id(self) -> str:
        """This printing's family-unique id, which ``pair_type`` indexes on."""
        return joined((self.version_code, self.source))

    @property
    def equivalent_xml_reference_id(self) -> str | None:
        """The twin's family-unique id, or ``None`` when this row names no twin."""
        if self.equivalent_xml_version_code is None or self.equivalent_xml_source is None:
            return None
        return joined((self.equivalent_xml_version_code, self.equivalent_xml_source))

    @property
    def format_name(self) -> str | None:
        """This repository's short name for the chosen link (``xml``, ``pdf``, ``txt``...)."""
        return None if self.chosen_format is None else format_name_of(self.chosen_format)

    @property
    def version_code_is_reprint_ambiguous(self) -> bool:
        """Whether the publisher's version-type string also names a different printing.

        A type the sealed vocabulary does not name is not ambiguous -- nothing
        else claims it -- and that refusal is answered here rather than left to
        abort a whole bill over one unrecognised printing.
        """
        version_type = self.version.type
        if not version_type:
            return False
        try:
            return len(version_slug_reprints(version_type)) > 0
        except VersionCodeError:
            return False


@dataclass(frozen=True, slots=True)
class BillFamilyCapture:
    """One bill's BILLSTATUS document and every printing acquired for it."""

    status: Any
    versions: tuple[BillVersionCapture, ...] = ()
    observed_at: str = ""


class SectionClassifier(Protocol):
    """``functools.partial(classify_sections, call=..., model=...)``, or a test stub."""

    def __call__(self, sections: Sequence[ClassifiableSection]) -> tuple[Any, ...]: ...


class BillSummarizer(Protocol):
    """``functools.partial(summarize_bill, call=..., model=...)``, or a test stub."""

    def __call__(self, version: BillVersionText) -> Any | None: ...


class DiffSummarizer(Protocol):
    """``functools.partial(summarize_diff, call=..., model=...)``, or a test stub."""

    def __call__(
        self,
        identity: Any,
        *,
        from_version_id: str,
        to_version_id: str,
        items: Sequence[DiffItemText],
    ) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class BillFamilyTables:
    """Every row one family pass produced, plus what it refused."""

    bills: tuple[Row, ...] = ()
    bill_actions: tuple[Row, ...] = ()
    bill_committees: tuple[Row, ...] = ()
    bill_publisher_summaries: tuple[Row, ...] = ()
    cbo_cost_estimates: tuple[Row, ...] = ()
    bill_versions: tuple[Row, ...] = ()
    bill_sections: tuple[Row, ...] = ()
    section_diffs: tuple[Row, ...] = ()
    section_diff_items: tuple[Row, ...] = ()
    financial_changes: tuple[Row, ...] = ()
    section_classifications: tuple[Row, ...] = ()
    bill_summaries: tuple[Row, ...] = ()
    diff_summaries: tuple[Row, ...] = ()
    refusals: tuple[FamilyRefusal, ...] = ()

    def merged(self, other: BillFamilyTables) -> BillFamilyTables:
        """This pass's rows followed by ``other``'s, field by field.

        Every field is a tuple, so one concatenation covers all of them and a
        table added later needs no second edit here; deduplication is the
        merge's job in spicy-regs, keyed on each contract's own identity, so
        nothing is dropped here. Pairwise and copying, so folding it over a run
        is quadratic in the number of bills -- a rollup accumulating one per
        bill calls :meth:`concat` once instead.
        """
        if not isinstance(other, BillFamilyTables):
            raise TypeError("merged takes another BillFamilyTables")
        return BillFamilyTables(
            **{name: getattr(self, name) + getattr(other, name) for name in BillFamilyTables.__dataclass_fields__}
        )

    @classmethod
    def concat(cls, families: Iterable[BillFamilyTables]) -> BillFamilyTables:
        """Every family's rows, in order, in one pass over each field.

        What a rollup over many bills uses: each row is copied once, so the
        cost is linear in the rows produced rather than quadratic as with
        :meth:`merged`.
        """
        collected: dict[str, list[Any]] = {name: [] for name in cls.__dataclass_fields__}
        for family in families:
            if not isinstance(family, BillFamilyTables):
                raise TypeError("concat takes BillFamilyTables values")
            for name, rows in collected.items():
                rows.extend(getattr(family, name))
        return cls(**{name: tuple(rows) for name, rows in collected.items()})


def classification_vocabulary_hash() -> str:
    """Digest over the sealed label table, so a vocabulary change is visible in the data.

    Both name and definition are hashed, because the definitions live only in
    the prompt and a re-worded definition changes what the model was asked even
    when every label name is unchanged.
    """
    material = "\n".join(f"{label.name}={label.definition}" for label in CLASSIFICATION_LABELS)
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def installed_engine_stamp(name: str = "deltatrack") -> EngineStamp:
    """The stamp for the diff engine this environment actually installed.

    Read from the distribution's own metadata rather than hand-typed: a git
    install records its resolved commit in ``direct_url.json``, while a wheel
    install states no commit and the stamp says so rather than reporting a
    revision it does not know. Raises :class:`BillFamilyError` when the
    distribution is not installed.
    """
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError as error:
        raise BillFamilyError(f"{name} is not installed; install the 'bill-diff' extra") from error
    revision = ""
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            revision = str(loads(direct_url).get("vcs_info", {}).get("commit_id", ""))
        except (JSONDecodeError, AttributeError):
            revision = ""
    return EngineStamp(name=name, version=distribution.version, revision=revision)


def section_reference(version_code: str, source: str, seq: int) -> str:
    """The id a section is sent to the model under, and mapped back from.

    Short and printable on purpose: it travels inside a prompt and comes back
    in the model's answer, so it is not the unit-separator-joined published key.
    """
    return f"{version_code}|{source}|{seq}"


def _walk_committees(committees: Iterable[Any], parent: str | None = None) -> Iterator[tuple[Any, str | None]]:
    """Every committee and subcommittee, each beside its immediate parent's code.

    Recursive to whatever depth the publisher states, which is the depth
    ``congress_bills.committee_count`` counts: a two-level walk would make that
    column disagree with the rows it claims to count. One traversal serves both
    the rows and the referral signals.
    """
    for committee in committees or ():
        yield committee, parent
        yield from _walk_committees(committee.subcommittees, committee.system_code)


def _referral_signal(system_code: str | None) -> str | None:
    if not system_code:
        return None
    signals = money_bills.referrals_from_committee_codes((system_code,))
    return next(iter(signals), None)


def _body_bytes(document: Any) -> int | None:
    if document is None:
        return None
    return sum(len((node.body_text or "").encode("utf-8")) for node in document.sections)


def _body_text(document: Any) -> str:
    return "\n\n".join(node.body_text for node in document.sections if node.body_text)


#: What a shaper is allowed to fail with before the failure becomes a refusal
#: rather than an abort.  ``VersionCodeError`` is the one this layer provoked in
#: practice -- a publisher version type the sealed vocabulary does not name --
#: and ``TypeError`` covers a record whose shape is not what the shaper reads.
#: Nothing wider: an exception outside these is a defect, and swallowing it
#: would turn a broken shaper into a quietly short table.
SHAPER_REFUSALS = (TableContractError, VersionCodeError, TypeError)


class _Admitter:
    """Shape one row, admit it if it satisfies its contract, and name why if it does not.

    The shaping happens inside the guard, because one unrecognised printing
    used to raise out of ``shape_bill_version`` and abort the whole bill;
    ``identity`` is what the refusal is filed under when there is no row to
    read one from. A row repeating the identity of one already admitted in
    this pass is refused rather than emitted twice.
    """

    def __init__(self) -> None:
        self.refusals: list[FamilyRefusal] = []
        self._admitted: dict[str, set[tuple[str, ...]]] = {}

    def __call__(
        self,
        contract: TableContract,
        rows: list[Row],
        identity: tuple[str, ...],
        build: Callable[[], Row],
    ) -> Row | None:
        try:
            row = build()
        except SHAPER_REFUSALS as error:
            self.refuse(contract.name, identity, f"the shaper refused this row: {error}")
            return None
        try:
            keyed = contract.key(row)
            checked = contract.checked(row)
        except TableContractError as error:
            self.refuse(contract.name, tuple(row.get(column) or "" for column in contract.identity), str(error))
            return None
        admitted = self._admitted.setdefault(contract.name, set())
        if keyed in admitted:
            # A host merge keeps one row per identity, so emitting both would
            # publish one and drop the other without a word.
            self.refuse(contract.name, keyed, "repeats the identity of a row this pass already admitted")
            return None
        admitted.add(keyed)
        rows.append(checked)
        return row

    def refuse(self, table: str, identity: tuple[str, ...], reason: str) -> None:
        # Pattern scrubbing also removes keys the caller never received. Do it
        # before bounding free text so a truncated key prefix cannot survive.
        self.refusals.append(FamilyRefusal(table=table, identity=identity, reason=scrub_credential(reason, "")[:2000]))


def _cost_estimate_refusal(url: object) -> str:
    """Describe a rejected locator without retaining its query, fragment or user info."""
    prefix = f"{PUBLICATION_ID_RULE}: cost-estimate url is outside the measured publication-page shape"
    if not isinstance(url, str):
        return f"{prefix}; url type={type(url).__name__}"
    try:
        parts = urlsplit(url)
        parsed_id = publication_id(parts._replace(query="", fragment="").geturl())
        shape = "/publication/{id}" if parsed_id else "/".join("{segment}" for _ in parts.path.split("/"))
        return f"{prefix}; host={parts.hostname or '(missing)'}; path shape={shape}"
    except ValueError:
        return f"{prefix}; malformed URL"


#: Returned in place of an answer the reader refused, so the caller can tell it
#: apart from the ``None`` a generator returns when it *declines* to ask. The
#: two are different facts and were filed as one before: a refused summary was
#: reported as a printing whose text was below the minimum, which was false.
_REFUSED = object()


def _model_answer(
    generate: Callable[[], Any], *, table: str, identity: tuple[str, ...], admit: _Admitter
) -> Any | None:
    """One model generator, run inside the guard the shapers already run inside.

    A ``ModelCallError`` is the reader refusing the model's answer -- a missing
    key, a label outside the sealed vocabulary, a section id the batch never
    sent -- which is a record about one printing, not a reason to lose the
    other thirteen tables, so it is filed and the pass continues. Only the
    message is filed: ``ModelCallError.details`` carries the answer itself,
    which is model prose about the document. Nothing wider is caught on
    purpose: a credential refusal must abort the run, and a transport failure
    establishes nothing about this printing.
    """
    try:
        return generate()
    except ModelCallError as error:
        admit.refuse(table, identity, f"the model's answer was refused: {error}")
        return _REFUSED


def _sorted_versions(versions: Iterable[BillVersionCapture]) -> list[BillVersionCapture]:
    """Order printings by ``bill_versions.printing_order``; the source breaks a remaining tie."""
    captures = sorted(versions, key=lambda capture: capture.source)
    return [captures[i] for i in printing_order([(c.version_code, c.version.date) for c in captures])]


#: Why a printing is refused whole. Refusing only its repeated rows once
#: published a mix: 119 HR 6644's two Senate engrossed amendments shared
#: ``engrossed-amendment-senate``, the second's first 198 sections were refused
#: as repeats of the first's 198, its last 78 were admitted under the same key,
#: and every comparison into or out of it named sections never published.
REPEATED_PRINTING_REASON = (
    "repeats the printing identity of an earlier printing of this bill, so none of its rows are published"
)


def _repeated_printings(ordered: Sequence[BillVersionCapture]) -> set[int]:
    """Positions of printings whose ``(version_code, source)`` an earlier printing already carries."""
    seen: set[tuple[str, str]] = set()
    repeated: set[int] = set()
    for position, entry in enumerate(ordered):
        printing = (entry.version_code, entry.source)
        if printing in seen:
            repeated.add(position)
        seen.add(printing)
    return repeated


def _kind_code(entry: BillVersionCapture) -> str:
    """The code a printing's kind is read from: a numbered reprint (``eas2``) is its stage's kind."""
    try:
        stage = version_slug(entry.version.type or "")
        reprint = printing_version_code(entry.version)
    except VersionCodeError:
        return entry.version_code
    return stage if entry.version_code == reprint != stage else entry.version_code


def build_bill_family(
    capture: BillFamilyCapture,
    *,
    engine: EngineStamp,
    classify: SectionClassifier | None = None,
    summarize: BillSummarizer | None = None,
    summarize_diff: DiffSummarizer | None = None,
    clock: Callable[[], datetime] | None = None,
    diff: bool = True,
    pair_amounts: bool = False,
    text_diff_cap: int = TEXT_DIFF_CAP_BYTES,
) -> BillFamilyTables:
    """Build every table one bill fills, in one pass.

    ``diff=False`` ships the family without the four diff tables -- the
    documented fallback for an environment that cannot vendor the engine -- and
    also skips ``summarize_diff``, which has nothing to read without a diff.
    ``pair_amounts=True`` fills ``financial_changes``, off by default because
    pairing two figures is a claim about an account that upstream declines to
    publish.
    """
    now = clock if clock is not None else _now
    admit = _Admitter()
    status = capture.status
    identity = status.identity
    key = bill_id(identity)

    # 1. What the publisher's committee referrals say about money, by system code.
    referrals = money_bills.referrals_from_committee_codes(
        committee.system_code for committee, _ in _walk_committees(status.committees) if committee.system_code
    )

    # 2. The three bill-level findings, each carrying its own provenance.
    stage = bill_stage.infer_stage(status.actions)
    signing = bill_stage.signed_date(status)
    money = money_bills.classify_money_bill(
        title=status.title,
        congress=identity.congress,
        bill_type=identity.bill_type,
        number=identity.number,
        referrals=referrals,
    )

    # 3. The four tables one BILLSTATUS document fills.
    bills: list[Row] = []
    admit(
        CONGRESS_BILLS,
        bills,
        (key,),
        lambda: shape_bill(status, referrals=referrals, stage=stage, signing=signing, money=money),
    )

    actions: list[Row] = []
    # The publisher states latestAction as a separate element carrying only a
    # date, a time and text, so the one action it names is found by matching
    # those, not by comparing whole records -- see ``latest_action_index``.
    latest = latest_action_index(status)
    for index, action in enumerate(status.actions):
        admit(
            BILL_ACTIONS,
            actions,
            (key, str(index)),
            partial(
                shape_bill_action,
                identity,
                action,
                action_index=index,
                is_latest=index == latest,
                stage=bill_stage.infer_stage_from_text(action.text),
            ),
        )

    committees: list[Row] = []
    for committee, parent in _walk_committees(status.committees):
        admit(
            BILL_COMMITTEES,
            committees,
            (key, committee.system_code or ""),
            partial(
                shape_bill_committee,
                identity,
                committee,
                parent_system_code=parent,
                update_date=status.update_date,
                referral_signal=_referral_signal(committee.system_code),
            ),
        )

    publisher_summaries: list[Row] = []
    for summary in status.summaries:
        admit(
            BILL_PUBLISHER_SUMMARIES,
            publisher_summaries,
            (key, summary.version_code or "", summary.action_date or ""),
            partial(shape_bill_publisher_summary, identity, summary),
        )

    # 3b. The fifth table the same document fills: the CBO cost-estimate
    # index.  Folded onto (bill, publication) first, because the publisher
    # states one publication twice on some bills and that is one estimate;
    # a url outside the measured /publication/{id} shape cannot be keyed and
    # is refused by name rather than published unidentified.
    estimates: list[Row] = []
    folded, unkeyable = fold_cbo_cost_estimates(status.cbo_cost_estimates)
    for index, url in unkeyable:
        admit.refuse(
            CBO_COST_ESTIMATES.name,
            (key, str(index)),
            _cost_estimate_refusal(url),
        )
    for entry in folded:
        admit(
            CBO_COST_ESTIMATES,
            estimates,
            (key, entry.publication_id),
            partial(
                shape_cbo_cost_estimate,
                identity,
                entry,
                report_citations=status.report_citations,
            ),
        )

    # 4-9. The printing tables, from the captures alone.
    summarize_version = (
        None
        if summarize is None
        else partial(_summarize_version, status=status, stage=stage, money=money, summarize=summarize)
    )
    printed = _printing_tables(
        identity,
        capture.versions,
        admit=admit,
        engine=engine,
        classify=classify,
        summarize_version=summarize_version,
        summarize_diff=summarize_diff,
        now=now,
        diff=diff,
        pair_amounts=pair_amounts,
        text_diff_cap=text_diff_cap,
    )
    return replace(
        printed,
        bills=tuple(bills),
        bill_actions=tuple(actions),
        bill_committees=tuple(committees),
        bill_publisher_summaries=tuple(publisher_summaries),
        cbo_cost_estimates=tuple(estimates),
        refusals=tuple(admit.refusals),
    )


def build_bill_printings(
    identity: Any,
    versions: Iterable[BillVersionCapture],
    *,
    engine: EngineStamp,
    context: Collection[tuple[str, str]] = (),
    classify: SectionClassifier | None = None,
    summarize_diff: DiffSummarizer | None = None,
    clock: Callable[[], datetime] | None = None,
    diff: bool = True,
    pair_amounts: bool = False,
    text_diff_cap: int = TEXT_DIFF_CAP_BYTES,
) -> BillFamilyTables:
    """Build one bill's printing tables without its BILLSTATUS: versions, sections and comparisons.

    For a caller that acquires bodies apart from status -- a bulk text zip read
    once for every printing it holds -- and so has the printings but not a fresh
    status document. ``versions`` is every listed printing of the bill, in any
    order: captured ones with their documents, and the rest as placeholders
    without, so a comparison never skips a printing. ``context`` names printings
    by ``(version_code, source)`` that emit no version, section or model rows of
    their own: placeholders, and held printings whose documents are here only to
    be compared with a newly captured neighbour.
    Only the model work that needs no status runs (``classify``,
    ``summarize_diff``); a plain-language summary needs the status's stage and
    money-bill finding and stays with :func:`build_bill_family`.
    """
    admit = _Admitter()
    tables = _printing_tables(
        identity,
        versions,
        admit=admit,
        engine=engine,
        classify=classify,
        summarize_version=None,
        summarize_diff=summarize_diff,
        now=clock if clock is not None else _now,
        diff=diff,
        pair_amounts=pair_amounts,
        text_diff_cap=text_diff_cap,
        context=frozenset(context),
    )
    return replace(tables, refusals=tuple(admit.refusals))


def _printing_tables(
    identity: Any,
    versions: Iterable[BillVersionCapture],
    *,
    admit: _Admitter,
    engine: EngineStamp,
    classify: SectionClassifier | None,
    summarize_version: Callable[..., None] | None,
    summarize_diff: DiffSummarizer | None,
    now: Callable[[], datetime],
    diff: bool,
    pair_amounts: bool,
    text_diff_cap: int,
    context: Collection[tuple[str, str]] = frozenset(),
) -> BillFamilyTables:
    """Steps 4-9 of the family, shared by :func:`build_bill_family` and :func:`build_bill_printings`.

    A ``context`` printing takes part only in ordering and, with a document, as
    a side of a comparison; its own rows are left to the pass that listed or
    captured it, and so is a pair of two context printings the caller supplied
    no documents for.
    """
    key = bill_id(identity)
    # 4. One row per acquired printing, with the kind it classifies as. A
    # printing repeating an earlier one's identity is refused whole, here and in
    # every later step, rather than row by row.
    ordered = _sorted_versions(versions)
    repeated = _repeated_printings(ordered)
    versions_rows: list[Row] = []
    kinds: dict[tuple[str, str], Any] = {}
    for position, entry in enumerate(ordered):
        if position in repeated:
            admit.refuse(BILL_VERSIONS.name, (key, entry.version_code, entry.source), REPEATED_PRINTING_REASON)
            continue
        document = entry.document
        finding = version_kind.version_kind_finding(
            _kind_code(entry),
            section_count=None if document is None else len(document.sections),
            body_bytes=_body_bytes(document),
        )
        kinds[(entry.version_code, entry.source)] = finding
        if (entry.version_code, entry.source) in context:
            continue
        admit(
            BILL_VERSIONS,
            versions_rows,
            (key, entry.version_code, entry.source),
            partial(
                shape_bill_version,
                entry,
                identity=identity,
                kind=finding,
                kind_label=version_kind.VERSION_KIND_LABELS.get(finding.kind),
                kind_warning=version_kind.VERSION_KIND_WARNINGS.get(finding.kind),
            ),
        )

    # 5. One row per content-bearing node, and the map a model answer resolves through.
    sections: list[Row] = []
    section_by_reference: dict[str, Row] = {}
    for position, entry in enumerate(ordered):
        if position in repeated or (entry.version_code, entry.source) in context:
            continue
        if entry.document is None:
            admit.refuse(
                BILL_SECTIONS.name,
                (key, entry.version_code, entry.source),
                "no parsed document: the printing was not read as XML, so it has no sections",
            )
            continue
        version_date = entry.version.date
        for seq, node in enumerate(entry.document.sections):
            row = admit(
                BILL_SECTIONS,
                sections,
                (key, entry.version_code, entry.source, str(seq)),
                partial(
                    shape_bill_section,
                    node,
                    bill_id=key,
                    version_code=entry.version_code,
                    source=entry.source,
                    seq=seq,
                    version_date=version_date,
                ),
            )
            if row is not None:
                section_by_reference[section_reference(entry.version_code, entry.source, seq)] = row

    # 6. Consecutive pairs only: the diff is the one superlinear step in the family.
    diffs: list[Row] = []
    diff_items: list[Row] = []
    financials: list[Row] = []
    compared: list[tuple[BillVersionCapture, BillVersionCapture, Any]] = []
    if diff:
        compared = _diff_pairs(
            ordered,
            key=key,
            engine=engine,
            admit=admit,
            diffs=diffs,
            diff_items=diff_items,
            financials=financials,
            pair_amounts=pair_amounts,
            text_diff_cap=text_diff_cap,
            computed_at=now().isoformat(),
            withheld=repeated,
            context=context,
        )

    # 7-8. The per-printing model tables, only where a printing carries bill text.
    classifications: list[Row] = []
    summaries: list[Row] = []
    vocabulary = classification_vocabulary_hash()
    for position, entry in enumerate(ordered):
        if position in repeated or (entry.version_code, entry.source) in context:
            continue
        finding = kinds[(entry.version_code, entry.source)]
        if entry.document is None or finding.kind not in MODELLED_KINDS:
            continue
        if classify is not None:
            _classify_version(
                entry,
                classify=classify,
                section_by_reference=section_by_reference,
                vocabulary_hash=vocabulary,
                admit=admit,
                rows=classifications,
                bill_key=key,
            )
        if summarize_version is not None:
            summarize_version(entry, admit=admit, rows=summaries, bill_key=key)

    # 9. One diff summary per compared pair, from the comparison already in hand.
    diff_summaries: list[Row] = []
    if summarize_diff is not None:
        for older, newer, comparison in compared:
            _summarize_pair(
                older,
                newer,
                comparison,
                identity=identity,
                kinds=kinds,
                summarize_diff=summarize_diff,
                admit=admit,
                rows=diff_summaries,
                bill_key=key,
            )

    return BillFamilyTables(
        bill_versions=tuple(versions_rows),
        bill_sections=tuple(sections),
        section_diffs=tuple(diffs),
        section_diff_items=tuple(diff_items),
        financial_changes=tuple(financials),
        section_classifications=tuple(classifications),
        bill_summaries=tuple(summaries),
        diff_summaries=tuple(diff_summaries),
    )


def _diff_pairs(
    ordered: Sequence[BillVersionCapture],
    *,
    key: str,
    engine: EngineStamp,
    admit: _Admitter,
    diffs: list[Row],
    diff_items: list[Row],
    financials: list[Row],
    pair_amounts: bool,
    text_diff_cap: int,
    computed_at: str,
    withheld: Collection[int] = (),
    context: Collection[tuple[str, str]] = frozenset(),
) -> list[tuple[BillVersionCapture, BillVersionCapture, Any]]:
    """Diff each consecutive pair, or refuse the pair by name.

    A pair of two ``context`` printings is compared only when the caller
    supplied both documents, which is how it asks for that pair; otherwise the
    pair belongs to the pass that captured them and nothing is filed for it.

    Returns each comparison beside the two printings it compared, so the diff
    summary reads the engine's own records rather than the rows this pass just
    published. Imports ``section_diff`` inside the call because a family built
    with ``diff=False`` must import cleanly without the ``bill-diff`` extra.
    """
    from spicy_docs.interpretation import section_diff as diff_module

    compared: list[tuple[BillVersionCapture, BillVersionCapture, Any]] = []

    refs = [
        diff_module.VersionRef(
            version_id=entry.reference_id,
            source=entry.source,
            equivalent_xml_version_id=entry.equivalent_xml_reference_id,
        )
        for entry in ordered
    ]
    established = set(consecutive_pairs([(entry.version_code, entry.version.date) for entry in ordered]))
    for position in range(len(ordered) - 1):
        older, newer = ordered[position], ordered[position + 1]
        pair = (key, older.version_code, older.source, newer.version_code, newer.source)
        if (
            (older.version_code, older.source) in context
            and (newer.version_code, newer.source) in context
            and (older.document is None or newer.document is None)
        ):
            continue
        if position in withheld or position + 1 in withheld:
            admit.refuse(SECTION_DIFFS.name, pair, f"a side of the pair {REPEATED_PRINTING_REASON}")
            continue
        if (position, position + 1) not in established:
            admit.refuse(
                SECTION_DIFFS.name,
                pair,
                "neither a date nor a stage places a side of the pair, so which printing is earlier is not established",
            )
            continue
        if older.document is None or newer.document is None:
            admit.refuse(
                SECTION_DIFFS.name,
                pair,
                "a side of the pair has no parsed document, so the two printings cannot be compared",
            )
            continue
        try:
            kind = diff_module.pair_type(older.reference_id, newer.reference_id, refs)
            comparison = diff_module.diff_sections(
                older.document,
                newer.document,
                from_version=older.version_code,
                to_version=newer.version_code,
                pair_amounts=pair_amounts,
            )
        except diff_module.SectionDiffError as error:
            admit.refuse(SECTION_DIFFS.name, pair, str(error))
            continue
        admit(
            SECTION_DIFFS,
            diffs,
            pair,
            partial(
                shape_section_diff,
                comparison,
                bill_id=key,
                from_ref=older,
                to_ref=newer,
                from_version_date=older.version.date,
                to_version_date=newer.version.date,
                pair_type=kind,
                engine=engine,
                computed_at=computed_at,
            ),
        )
        for item in comparison.items:
            row = admit(
                SECTION_DIFF_ITEMS,
                diff_items,
                (*pair, str(item.seq)),
                partial(
                    shape_section_diff_item,
                    item,
                    bill_id=key,
                    from_ref=older,
                    to_ref=newer,
                    text_diff_cap=text_diff_cap,
                ),
            )
            if row is None:
                continue
            financial = item.financial
            for amount_index, amounts in enumerate(() if financial is None else financial.pairs):
                admit(
                    FINANCIAL_CHANGES,
                    financials,
                    (*pair, str(item.seq), str(amount_index)),
                    partial(shape_financial_change, amounts, item_key=row, amount_index=amount_index),
                )
        compared.append((older, newer, comparison))
    return compared


def _summarize_pair(
    older: BillVersionCapture,
    newer: BillVersionCapture,
    comparison: Any,
    *,
    identity: Any,
    kinds: dict[tuple[str, str], Any],
    summarize_diff: DiffSummarizer,
    admit: _Admitter,
    rows: list[Row],
    bill_key: str,
) -> None:
    """One ``diff_summaries`` row per compared pair, with the route's own guards applied.

    BillTrax's summarize route refuses a pair when either side is a procedural
    document, because summarizing edit instructions as if they were bill text
    produces confident nonsense; that guard reads ``bill_versions.kind``, which
    the generator is never handed, so it is applied here as a named refusal
    rather than a silent skip.
    """
    pair = (bill_key, older.version_code, older.source, newer.version_code, newer.source)
    procedural = [
        entry.version_code
        for entry in (older, newer)
        if kinds[(entry.version_code, entry.source)].kind not in MODELLED_KINDS
    ]
    if procedural:
        admit.refuse(
            DIFF_SUMMARIES.name,
            pair,
            f"not summarized: {', '.join(procedural)} does not carry bill text, "
            "and summarizing edit instructions as bill text is the failure this guard exists for",
        )
        return
    result = _model_answer(
        partial(
            summarize_diff,
            identity,
            from_version_id=older.version_code,
            to_version_id=newer.version_code,
            items=tuple(
                DiffItemText(
                    op=item.op,
                    # The adapter composes one heading, preferring the later
                    # printing's, which is the side the generator reads first.
                    from_heading=None,
                    to_heading=item.heading or None,
                    from_body=item.from_text,
                    to_body=item.to_text,
                )
                for item in comparison.items
            ),
        ),
        table=DIFF_SUMMARIES.name,
        identity=pair,
        admit=admit,
    )
    if result is _REFUSED:
        return
    if result is None:
        admit.refuse(
            DIFF_SUMMARIES.name,
            pair,
            "the diff-summary generator declined this pair; every settled correspondence is unchanged",
        )
        return
    admit(
        DIFF_SUMMARIES,
        rows,
        pair,
        partial(shape_diff_summary, result, from_source=older.source, to_source=newer.source),
    )


def _classify_version(
    entry: BillVersionCapture,
    *,
    classify: SectionClassifier,
    section_by_reference: dict[str, Row],
    vocabulary_hash: str,
    admit: _Admitter,
    rows: list[Row],
    bill_key: str,
) -> None:
    """One printing's labels, or a named refusal per answer this pass cannot store.

    Refusals are filed under the bill key first, like every other refusal the
    pass files, so a rollup collecting refusals across bills can say which bill
    a printing belonged to.
    """
    classifiable = [
        ClassifiableSection(
            section_id=section_reference(entry.version_code, entry.source, seq),
            body=node.body_text or "",
            heading=node.header_text or None,
        )
        for seq, node in enumerate(entry.document.sections)
    ]
    if not classifiable:
        return
    # A refusal in any batch loses the batches already read: `classify_sections`
    # returns its rows only when every batch has been read, which is its own
    # contract and not this layer's to second-guess. One refusal is filed for
    # the printing.
    results = _model_answer(
        partial(classify, classifiable),
        table=SECTION_CLASSIFICATIONS.name,
        identity=(bill_key, entry.version_code, entry.source),
        admit=admit,
    )
    if results is _REFUSED:
        return
    for result in results:
        section = section_by_reference.get(result.section_id)
        if section is None:
            admit.refuse(
                SECTION_CLASSIFICATIONS.name,
                (bill_key, entry.version_code, entry.source, result.section_id),
                "the model named a section this pass did not publish a row for",
            )
            continue
        admit(
            SECTION_CLASSIFICATIONS,
            rows,
            (*BILL_SECTIONS.key(section), result.label),
            partial(
                shape_section_classification,
                result,
                section_key=section,
                vocabulary_hash=vocabulary_hash,
            ),
        )


def _summarize_version(
    entry: BillVersionCapture,
    *,
    status: Any,
    stage: Any,
    money: Any,
    summarize: BillSummarizer,
    admit: _Admitter,
    rows: list[Row],
    bill_key: str,
) -> None:
    """One ``bill_summaries`` row, or a named refusal when the summarizer declines."""
    result = _model_answer(
        partial(
            summarize,
            BillVersionText(
                identity=status.identity,
                version_id=entry.version_code,
                version_label=entry.version.type or entry.version_code,
                title=status.title,
                # The stage key, not the latest action's prose: it is a
                # published column, so a summary's stated status is checkable
                # against a row.
                status=stage.stage,
                text=_body_text(entry.document),
                money_bill_kind=money.kind,
            ),
        ),
        table=BILL_SUMMARIES.name,
        identity=(bill_key, entry.version_code, entry.source),
        admit=admit,
    )
    if result is _REFUSED:
        return
    if result is None:
        admit.refuse(
            BILL_SUMMARIES.name,
            (bill_key, entry.version_code, entry.source),
            "the summarizer declined this printing; its text is below the minimum it will summarize",
        )
        return
    admit(
        BILL_SUMMARIES,
        rows,
        (bill_key, entry.version_code, entry.source),
        partial(
            shape_bill_summary,
            result,
            source=entry.source,
            money_bill_kind=money.kind,
            frame=frame_for_kind(money.kind),
        ),
    )


__all__ = [
    "MODELLED_KINDS",
    "REPEATED_PRINTING_REASON",
    "BillFamilyCapture",
    "BillFamilyError",
    "BillFamilyTables",
    "BillSummarizer",
    "BillVersionCapture",
    "DiffSummarizer",
    "EngineStamp",
    "FamilyRefusal",
    "SectionClassifier",
    "build_bill_family",
    "build_bill_printings",
    "classification_vocabulary_hash",
    "installed_engine_stamp",
    "section_reference",
]
