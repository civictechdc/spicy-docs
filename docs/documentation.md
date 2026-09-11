# Documentation maintenance

Maintain `README.md`, `CONTRIBUTING.md`, and the short guides in `docs/` with the
code they describe. Update `docs/architecture.md` when ownership changes,
`docs/cli.md` when commands change, and `docs/decisions.md` when source rules
change. Keep a short current rule and its reason beside unusual code.

The wiki is a generated reference snapshot with subsequent manual corrections.
`wiki/metadata.json` records source commit
`78b8565b936981308e8816821aefc59fab13635b`, generation time 2026-09-03, model, and
generator version `1.0.1`. The generator command and configuration are not
retained here. Exact automated regeneration is not currently reproducible;
do not invent a command or relabel old pages as current.

For a reference refresh:

1. Record the reviewed source revision and affected pages.
2. Read the implementation, callers, and relevant tests. Regenerate the affected
   explanation from this evidence; preserve the original snapshot metadata.
3. Add a page-level “Reviewed against” revision and identify manual corrections.
   Keep maintained task guides separate from generated inventories.
4. Check paths, links, and commands. Check claims about completeness, optional
   imports, and failure behavior against tests.

This manual procedure produces reviewable updates. Recovering the original
versioned generator command and configuration remains separate work. A small
source fix need not rewrite the whole wiki; link to current ownership instead
of copying function lists.
