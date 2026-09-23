"""The printed CFR ``part.section`` number grammar, importable without the CFR source package.

One grammar serves the annual granule selector (``sources.cfr.models``) and the
reconstruction parser's section heading (``reconstruction.parse``). Lettered
parts (``261a.1``), parenthesized (``1.401(k)-1``) and ranged numbers are
outside it; ``sources.cfr.annual.split_annual_cfr_section`` reads every printed
form.
"""

CFR_SECTION_NUMBER = r"[0-9]+(?:-[0-9]+)*\.[0-9]+[A-Za-z]?(?:-[0-9]+[A-Za-z]?)*"
