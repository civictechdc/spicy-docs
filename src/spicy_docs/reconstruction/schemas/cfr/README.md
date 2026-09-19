# CFR schema bundle

The XML Schema GovInfo publishes for annual CFR XML, pinned by digest and read
by `spicy_docs.reconstruction.validate` with no network access. A section
granule declares it as `xsi:noNamespaceSchemaLocation="CFRMergedXML.xsd"`.

| File | Publisher address | Bytes | SHA-256 | Fetched |
| --- | --- | ---: | --- | --- |
| `CFRMergedXML.xsd` | <https://www.govinfo.gov/bulkdata/CFR/resources/CFRMergedXML.xsd> (listed by <https://www.govinfo.gov/bulkdata/json/CFR/resources>, last modified 2026-06-24 per that listing) | 248,366 | `1f400461602beda201e902268cdab4df4d4c5af88f47bbb760f74a3415ac6ae2` | 2026-09-19 |

The schema is self-contained: it declares no `xs:import` or `xs:include`, so
the local catalog in `validate.py` has one entry and refuses every other
resolution. The same directory on the publisher also lists `CFRDOC.DTD`
(139,336 bytes), `cfr.xsl` and the guide as PDF; only the XSD is pinned
because it is the schema the published granules name. The bundle's digest is
stated once more in `profiles.py` and a test checks the two agree.
