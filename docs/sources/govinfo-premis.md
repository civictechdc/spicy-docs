# Read GovInfo preservation metadata

Use `read_govinfo_premis` for retained GovInfo PREMIS 2 XML. It preserves every
object, including files without a published digest. A separate
`compare_govinfo_premis` helper compares a captured file's SHA-256 to one
unambiguous publisher statement. Both functions work without HTTP dependencies.

## Source fields

| View | Preserved source data |
| --- | --- |
| `GovInfoPremisRead` | Complete root tree, input digest/size, element count and all direct object views. |
| `PremisObject.object_type` | Literal `xsi:type`, including unfamiliar or prefixed values. |
| `identifiers` | Every `objectIdentifier`, with its type/value children. |
| `characteristics` | Every characteristics block, including composition level, size, formats and extensions. |
| `fixities` | Every nested fixity, including algorithm, digest and originator. Its tree path identifies the containing characteristics block. |
| `original_names`, `storage` | Repeated names, locations, location labels and storage metadata. |
| `element` / `fields(*path)` | All other source fields, including relationships, events, agents and unknown namespaces. Bare names in `fields` mean PREMIS 2. |

The shared `XmlTreeElement` retains attributes, namespace declarations, ordered
mixed content and one-based element-child positions. Its `leading_text` matches
ElementTree's `.text`; `text` includes descendant text. Direct `findall` uses
expanded names, such as `{info:lc/xmlns/premis-v2}messageDigest`. XML parsing
decodes character references and predefined entities, and normalizes XML line
endings. DTD and entity declarations are refused. Original bytes preserve
comments, prefix spelling and other lexical details.

The [Library of Congress PREMIS 2 dictionary](https://www.loc.gov/standards/premis/v2/premis-2-0.pdf)
defines the source groups. A characteristics block's `compositionLevel`
describes its encoding layer; level zero is the base form. The reader maps
source data without XSD validation or downloading `schemaLocation`. It retains
missing, empty and repeated values. PREMIS 3 uses a different namespace and is
explicitly outside this reader's current scope.

## Compare retained bytes

This runnable example takes a PREMIS file, a captured body file and that body's
capture JSON. The JSON supplies `requested_url`, `resolved_url`, `status_code`,
`content_type`, `observed_at`, `content_encoding`, `method`, `sha256` and
`byte_size` from the original capture. Keep the method and response metadata;
a filename alone cannot establish which response was received.

```sh
uv run --frozen python - package.premis.xml rendition.xml rendition.capture.json <<'PY'
import json
import sys
from pathlib import Path

from spicy_docs.sources.govinfo.premis import read_govinfo_premis, compare_govinfo_premis
from spicy_docs.transport.captured import CapturedBodyResponse

metadata = read_govinfo_premis(Path(sys.argv[1]).read_bytes())
details = json.loads(Path(sys.argv[3]).read_text())
capture = CapturedBodyResponse(
    **{key: details[key] for key in (
        "requested_url", "resolved_url", "status_code", "content_type",
        "observed_at", "content_encoding", "method",
    )},
    body=Path(sys.argv[2]).read_bytes(),
)
assert capture.byte_size == details["byte_size"]
assert capture.sha256 == "sha256:" + details["sha256"].removeprefix("sha256:")
comparison = compare_govinfo_premis(capture, metadata)
print(metadata.source_sha256, len(metadata.objects))
print(comparison.status, comparison.reason)
PY
```

Comparison requires a complete, unencoded HTTP 200 GET response. Its resolved
URL must match the single absolute HTTP(S) URI token in a URI-typed source
location. The publisher's surrounding location label remains unchanged in the
tree. Optional `original_name` further narrows the same URL selection and
requires one scalar name; it never substitutes for a matching URL.

Exactly one file object and one SHA-256 fixity in its own level-zero block must
remain. Repeated or malformed competing names, algorithms and relevant location
claims produce `not-comparable` with a reason. Other reasons distinguish missing
fixity, unsupported composition, a different URL and unsupported capture state.
`consistent` or `mismatch` compares SHA-256 only; published sizes remain raw
metadata. Agreement establishes consistency with the publisher's statement,
not authenticity or correctness of the document.

Defaults bound XML at 16 MiB, 100,000 elements and depth 64, including unknown
fields. The reader performs one XML scan and retains one tree. It does not
fetch files, store a release, mint identifiers or choose a catalog population.

The committed complete CFR fixture contains 46 objects: 33 files and 13
representations. Only three files have fixity statements; all 30 others remain
visible. These counts describe that retained package, not all GovInfo packages.
