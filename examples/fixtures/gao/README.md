# Synthetic GAO topic inputs

These three small HTML files are authored examples, not live publisher captures.
They use the same illustrative product URL and contain no redactions. Keep the
files unchanged when running an example; its output records the exact input
digest, and its blob store retains the accepted evidence ZIP or refused HTML.

| File | Source condition | Expected source result |
| --- | --- | --- |
| `matching.html` | One topic field says `Information Security` at `/topics/information-security` | Publish that literal topic. |
| `unexpected.html` | One topic field says `Agency Operations` at `/topics/agency-operations` | Publish that literal topic too; there is no allowed-topic list. |
| `missing.html` | A navigation topic exists, but the publisher topic field is absent | Refuse the collection and retain the bounded response for diagnosis. |

“Matching” and “unexpected” are relative to this example's `Information Security`
label. They are fixture names, not source classifications or selection rules.
DocSpec's D51 example owns any catalog filter or processing that uses a label.
Nothing here infers requirements, applicability or membership in a taxonomy.

From the repository root, run each case into its own new output directory:

```sh
uv run --frozen python examples/offline_release.py --case matching
uv run --frozen python examples/offline_release.py --case unexpected
uv run --frozen python examples/offline_release.py --case missing
```

The missing case completes the demonstration by returning its expected refusal;
it does not return a publication, source records or an accepted empty outcome.
An unrelated failure still stops the example with an error.
