"""Legacy report links published by the current FEC agency-report index.

Pins redirect preservation of source and final URLs, keyless requests, and
refusal of hosts the index does not approve.
"""

import httpx
import pytest

from spicy_docs.sources.fec.catalog import official_url
from spicy_docs.sources.fec.client import FecClient


@pytest.mark.parametrize("host", ["beta.fec.gov", "www.fec.gov"])
def test_report_redirect_preserves_source_and_final_url(tmp_path, host):
    """A report redirect preserves the source and final URL, writes the blob and makes no keyed request."""
    source = f"https://{host}/resources/foia/foiareport2015.xml"
    final = "https://www.fec.gov/resources/foia/foiareport2015.xml"
    calls = []
    body = b'<FoiaAnnualReport xmlns="urn:example:foia"/>'

    def serve(request):
        calls.append(str(request.url))
        assert "X-Api-Key" not in request.headers
        if request.url.host == "beta.fec.gov":
            return httpx.Response(301, headers={"location": final})
        return httpx.Response(200, content=body, headers={"content-type": "application/xml"})

    with FecClient(
        store=tmp_path, api_key="unused-api-key", min_interval=0, transport=httpx.MockTransport(serve)
    ) as client:
        asset = client.download(source, max_bytes=len(body))
    assert asset["url"] == source
    assert asset["response"]["resolved_url"] == final
    assert (tmp_path / asset["blob_path"]).read_bytes() == body
    assert calls == ([source, final] if host == "beta.fec.gov" else [source])


@pytest.mark.parametrize("host", ["beta.fec.gov.example", "other.fec.gov"])
def test_report_link_does_not_approve_other_hosts(tmp_path, host):
    """A report link does not approve other hosts."""
    target = f"https://{host}/report.xml"
    with pytest.raises(ValueError, match="approved"):
        official_url(target)
    with FecClient(
        store=tmp_path,
        min_interval=0,
        transport=httpx.MockTransport(lambda _: httpx.Response(301, headers={"location": target})),
    ) as client:
        with pytest.raises(ValueError, match="approved"):
            client.download("https://beta.fec.gov/resources/foia/foiareport2015.xml", max_bytes=1024)
        assert client.http.request_count == 1
