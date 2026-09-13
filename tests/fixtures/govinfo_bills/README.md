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
