# Read GovInfo metadata

SpicyDocs maps the complete GovInfo MODS record: package description, constituent
records, source links, and unfamiliar fields. MODS means **Metadata Object
Description Schema**. Document bodies remain separate acquisitions.

The [annual CFR metadata API](cfr.md#read-dates-and-identity-honestly) returns
`result.metadata` alongside the narrower `result.edition` interpretation and
`result.capture`. Parsing non-body source metadata belongs in SpicyDocs;
dataset selection and interpretation belong to its consumers.

## What the model preserves

| Object | Use |
| --- | --- |
| `GovInfoModsPackage` | Read `.package`, direct `.constituents`, and the input's `.source_sha256`, `.source_byte_size`, and `.element_count`. |
| `ModsRecord` | Read common field groups or use `.fields(*relative_names)` for any path. `.related_items` retains every relationship type, including nested records. |
| `ModsElement` | Read `.name`, `.attributes`, `.namespace_declarations`, ordered `.content`, and occurrence `.path`. `.children`, `.text`, `.attribute(name)`, and `.findall(*relative_names)` support inspection. |

Field groups contain repeated elements, not a single chosen value. `titles`
contains `titleInfo` elements; `origins` contains `originInfo` elements. Read
their children to keep each title or publication event together.

Unqualified path names select the MODS namespace. Expanded names distinguish
foreign elements and attributes, for example
`{http://www.w3.org/1999/xlink}href`. Namespaces are part of a field's identity.
Local namespace declarations retain their prefix/URI pairs; ancestors supply
inherited context. `.path` uses one-based element-child positions, starting at
`(1,)` for the root. It identifies an occurrence, not a byte offset.
Use `{}name` to select an element explicitly outside any namespace. Relative
URLs and inherited `xml:base`, `xml:lang` and `xml:space` remain source context;
the mapper does not resolve URLs or fetch linked documents.

Read a retained file without acquisition dependencies or network access:

```python
from pathlib import Path
from spicy_docs.sources.govinfo import parse_govinfo_mods

metadata = parse_govinfo_mods(Path("mods.xml").read_bytes(), max_bytes=2 * 1024 * 1024)
for date in metadata.package.fields("originInfo", "dateIssued"):
    print(date.text, date.attributes, date.path)
```

The pure parser defaults to 16 MiB, 100,000 elements and depth 64. Callers may
set `max_bytes` and `max_elements`; acquisition uses its explicit byte allowance.

## Standard MODS field map

Paths below are relative to `/mods` or a particular `relatedItem`. `@` denotes
an attribute. Every occurrence and its attributes remain available.

| Source path | Model access | Keep together |
| --- | --- | --- |
| `titleInfo` | `.titles` | `title`, `subTitle`, `nonSort`, repeated `partNumber`/`partName`, and title attributes. |
| `name` | `.names` | Repeated `namePart`, affiliations and roles, including each `roleTerm/@type` and `@authority`. |
| `identifier` | `.identifiers`; `.preferred_citations` filters `@type` | Text with its identifier type, source and other attributes. |
| `originInfo` | `.origins` | Publishers/agents, places, edition, frequency and every date with its event context. |
| `language` | `.languages` | Language terms with code system and text/code distinction. |
| `location`, `location/url` | `.locations`, `.urls` | URL text with `@displayLabel`, `@access`, and other qualifiers. A detail page and a rendition are different links. |
| `subject`, `note` | `.subjects`, `.notes` | Nested subject terms and their authorities; literal notes and note types. |
| `recordInfo` | `.record_info` | Record identifiers, creation/change dates, origin and cataloging language. |
| `relatedItem` | `.related_items` | Its `@type`, `@ID`, links and complete nested description. |
| `extension` | `.extensions` | Every publisher extension element, attribute and text segment. |
| `typeOfResource`, `genre`, `physicalDescription`, `abstract`, `tableOfContents`, `targetAudience`, `classification`, `accessCondition`, `part` | `.fields("elementName")` | All remaining standard groups, including nested content and attributes. |

The [MODS element guide](https://www.loc.gov/standards/mods/userguide/generalapp.html)
defines these groups. A `relatedItem` can contain another complete MODS description
or only a link; preserve both forms. Its relationship type is a source statement,
not an instruction to fetch the target.
[Related-item definitions](https://www.loc.gov/standards/mods/userguide/relateditem.html).

## GPO fields observed in annual CFR

Use `.fields("extension", "fieldName")` on the package or constituent record.
These are observed source paths, not a closed schema or a list of required fields.
GPO's [CFR field dictionary](https://www.govinfo.gov/help/cfr) explains
their search/display purpose; the retained MODS supplies the exact XML spelling.
These observed GPO extension elements inherit the MODS namespace even though
the standard schema does not define their individual meanings.

| Scope and source paths | Meaning to preserve |
| --- | --- |
| Package: `collectionCode`, `category`, `branch`, `docClass` | Publisher collection and classification labels. |
| Package: `accessId`, `titleNumber`, `volumeNumber`, `volumeCount`, `editionId` | Package identity, volume scope and edition grouping. |
| Package: `dateIngested`, `originalDateIssued`, `isCoverOnly`, `isCurrentEdition`, `isFallbackTitle` | Distinct repository/publication facts and publisher flags. |
| Package: `partRange/@from`, `@to`, `nodeRange`, `waisDatabaseName` | Literal bounds and source identifiers, including empty or historical fields. |
| Constituent: `accessId`, `sequenceNumber`, `granuleClass`, `granuleLabel`, `granuleNumber`, `searchTitle`, `heading` | Source identity, order, classification and display text. |
| Constituent: `chapterHeading`, `chapterTitle`, `partHeading`, `partTitle`, `subpartHeading`, `subpartTitle`, `subjectGroup` | Navigation context without reconstructing it from a section number. |
| Constituent: `partRange`, `leafRange`, `graphicsInPDF` | Scope and presentation hints; retain range attributes and missing flags. |
| Constituent: `authority`, `source`, `citation`, `editorialNotes` | Literal authority statements, source/amendment citations and notes. |
| Constituent: `USCode`, `cfr`, `fr`, `statuteAtLarge`, `law`, `presidentialDoc` | Structured reference hints. Preserve child fields and attributes such as `title`, `number`, `volume`, `pages`, `context`, `detail`, and `isPrivate`. |

Constituent `identifier[@type="Parent Id"]` values are available as
`.parent_ids`. `relatedItem[@type="otherFormat"]/@xlink:href` and `location/url`
can describe the same format through different source paths; both remain mapped.
Only direct `relatedItem[@type="constituent"]` records appear in `.constituents`.

## Read values faithfully

- **Keep repeated dates.** MODS dates may be text, partial dates or ranges.
  Retain `@encoding`, `@point`, `@qualifier`, `@keyDate`, and `@calendar` with
  each occurrence. The general mapper leaves values as strings; an annual CFR
  edition check applies its narrower source rules separately.
  [Date definitions](https://www.loc.gov/standards/mods/userguide/origininfo.html).
- **Keep text around child elements.** `.content` retains the ordered mixture
  of text and child elements, including whitespace. `.text` is convenient for
  scalar fields; it does not replace the structured value.
- **Keep unfamiliar fields and values.** Both the publisher's declared
  [MODS 3.3 schema](https://www.loc.gov/standards/mods/v3/mods-3-3.xsd) and
  [MODS 3.8](https://www.loc.gov/standards/mods/v3/mods-3-8.xsd) allow mixed,
  repeated extension content. The general mapper checks safe XML and the MODS
  root, without validating against an XSD, coercing vocabulary values or
  downloading schemas named by `xsi:schemaLocation`. Selected CFR edition
  identity/date checks remain separate.
- **Retain the original bytes.** XML parsing resolves character references and
  normalizes XML line endings. Prefix spelling, CDATA boundaries, comments and
  processing instructions remain in `result.capture.body`; the element model
  preserves parsed content, not byte-identical XML serialization.

## Use the inventory without overstating it

The retained 2023 and 2025 Title 1 records each describe 401 constituents,
including 288 section entries. They advertise 391 XML and 400 PDF links.
Those counts describe these metadata files; they establish neither downloaded
bodies nor publisher-wide completeness.

Publisher hints can disagree: the 2025 Chapter VI metadata uses
`extension/cfr/part/@number="VI"`; the 2023 record uses `cfr/chapter` instead.
Preserve those statements for comparison. A successful metadata parse does not
make every citation a validated address.

SpicyDocs owns faithful parsing and acquisition evidence. DocSpec can turn these
records into selected catalog items and track subsequent captures. RefSpec or
another processor interprets references and checks them against body text.
See [source ownership](../source-ownership.md).

This API maps MODS descriptive metadata. GovInfo separately provides PREMIS
preservation metadata and METS package metadata; those files are outside this
parser. [GovInfo package definitions](https://www.govinfo.gov/features/api).
