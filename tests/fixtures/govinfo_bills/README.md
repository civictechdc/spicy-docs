# GovInfo bill parser samples

Retrieved from GovInfo with unauthenticated GET on 2026-09-12. These U.S.
government documents are public domain. Offline tests establish behavior for
these shapes; they do not establish coverage or continuing live availability.

| Fixture | Publisher response | Changes |
| --- | --- | --- |
| `status-119hr6028.xml` | [119 HR 6028 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr6028.xml) | Omitted unrelated fields, retained two actions and two subjects, shortened each summary to its first HTML paragraph, reformatted XML. Both offered text versions remain. |
| `text-119hr6028eh.xml` | [119 HR 6028 EH XML](https://www.govinfo.gov/content/pkg/BILLS-119hr6028eh/xml/BILLS-119hr6028eh.xml) | Retained identity fields and first section, omitted other content, reformatted XML. External DOCTYPE retained. |
| `text-119hr6028ih.xml` | [119 HR 6028 IH XML](https://www.govinfo.gov/content/pkg/BILLS-119hr6028ih/xml/BILLS-119hr6028ih.xml) | Same reduction; preserves the introduced version and its root stage. |
| `text-119s5enr.xml` | [119 S 5 ENR XML](https://www.govinfo.gov/content/pkg/BILLS-119s5enr/xml/BILLS-119s5enr.xml) | Same reduction; preserves spelled-out Congress and title without Congress number. |
| `text-119hjres25enr.xml` | [119 HJRES 25 ENR XML](https://www.govinfo.gov/content/pkg/BILLS-119hjres25enr/xml/BILLS-119hjres25enr.xml) | Complete, unchanged 2,751-byte response. |

Full response SHA-256 values, before reduction:

```text
status-119hr6028 190296c4c420dd547ffdf5835352a8830e901d729729eaab432a9e6a65ff9aa7
text-119hr6028eh 89f7d7a3a1f3fe28bc5227099662d8819ba674c70ccb258edba16ada7d3fc21d
text-119hr6028ih 6cf3e83e9ef2788fadfc205ecd081f12f2306742528e4f9d4eac6047c7555ff5
```

Complete response bytes, hashes, and HTTP receipts remain outside the repository
in the `bill-parser-probe-2026-09-12` corpus receipt directory.

## Bulk archive members

Complete, unchanged members of
[`BILLSTATUS-119-hres.zip`](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hres/BILLSTATUS-119-hres.zip)
(3,934,575 bytes, SHA-256
`fe82a63f30b55086556ba4192eef973eadc91cbb94186f471f84af1f0354506a`,
`content-type: application/zip`, publisher Last-Modified 2026-09-18 20:26:06
GMT), retrieved with unauthenticated GET on 2026-09-19. The three carry the
shapes `read_bulk_status_archive` has to read; the tests build their own small
zip from them, so the archive under test is exactly these bytes. Each one was
also fetched from its own single-file locator on the same day and is
byte-identical there, so the zip member and the published file are one object.

| Fixture | Archive member | Bytes | SHA-256 | Why it is here |
| --- | --- | --- | --- | --- |
| `status-119hres1376.xml` | `BILLSTATUS-119hres1376.xml` | 5,230 | `46700c14cde7b16178df2f63373ea0b75b24343c9be6afcfebee5a7166f0999a` | The current common shape: one summary whose `<text>` is a direct child. |
| `status-119hres10.xml` | `BILLSTATUS-119hres10.xml` | 8,109 | `b820f778ba01657db0f1013ffa0541da4e97365e725a8762b6f053b2267c8175` | Its summary states `<text>` inside a `<cdata>` element; 984 of 12,938 measured files do. |
| `status-119hres214.xml` | `BILLSTATUS-119hres214.xml` | 6,181 | `d4ffc66661530ca10370fc0893e52c18b0c841cdd3d4667494ba6d12f438c49d` | An action item states `actionCode` and `sourceSystem` with no `<text>`; 7 of 12,938 do. |

Both shapes are [decision 4, measured](../../../docs/sources/congress-bulk-status.md#decision-4-measured).
The whole-zip measurement, its per-type counts and the H.R. and S.Res. zips it
also covers stay outside the repository.
