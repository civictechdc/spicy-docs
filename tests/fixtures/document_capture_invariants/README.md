# Owner capture counterexamples

Copied without changes from Rulespec `21693e0a`,
`release-records/fixtures/document-capture-v1/negative-{child-before-parent,duplicate-node-id}.json`.
These bounded documents isolate the two invariant defects accepted by the
previous copied validator. The adoption test invokes the installed owner
validator and requires the specific finding, then repairs the input and
requires acceptance. No publisher acquisition is involved.
