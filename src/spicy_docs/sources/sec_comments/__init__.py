"""SEC rulemaking public comments from sec.gov's own comment pages: index, listings, files, reader.

The rulemaking index at ``/rules-regulations/rulemaking-activity`` states
rule-page links and file numbers where present. Each rule page's received-
comments field supplies its listing URLs. Listings state letter-type sections
and comment files and paginate with ``?page=N``. The legacy file-number
selection remains available with an explicitly derived listing URL. The modules:

* :mod:`.pages` -- the three HTML shapes, their locators and their identity checks.
* :mod:`.acquisition` -- the declared fair-access agent, the paced bounded
  acquirer and the file-body proofs (``%PDF-`` magic, trailer and cross-reference checks,
  HTML's opening tag and the docket in the file's own words).
* :mod:`.reader` -- the ``Reader`` whose keys are file URLs.
* :mod:`.join` -- connects rulemakings, retained regulations.gov SEC
  documents and comment files, with provenance at every hop.
"""
