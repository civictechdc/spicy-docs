"""Small, source-owned route declarations; no dataset or document catalog."""

import json
from importlib.resources import files
from urllib.parse import parse_qsl, unquote, urlsplit

API_ROOT = "https://api.open.fec.gov"
BUCKET = "cg-519a459a-0ea3-42c2-b7bc-fa1143481f74"
BUCKET_URL = f"https://{BUCKET}.s3-us-gov-west-1.amazonaws.com/"
SITEMAPS = (
    "https://www.fec.gov/sitemap-wagtail.xml",
    "https://www.fec.gov/resources/cms-content/documents/sitemap_pdf.xml",
    "https://www.fec.gov/resources/cms-content/documents/sitemap_html.xml",
)
PREFIXES = ("bulk-downloads/", "legal/", "user-downloads/")


def official_sources() -> list[dict]:
    return json.loads(files(__package__).joinpath("official_sources.json").read_text())


def api_operations() -> dict[str, str | list[str]]:
    return json.loads(files(__package__).joinpath("api_operations.json").read_text())


def official_url(url: str) -> str:
    """Permit public FEC hosts and the exact published bucket; reject credentials."""
    p = urlsplit(url)
    hosts = {"www.fec.gov", "fec.gov", "api.open.fec.gov", "docquery.fec.gov", "sers.fec.gov", "transition.fec.gov"}
    hosts.add(urlsplit(BUCKET_URL).hostname)
    if p.scheme != "https" or p.hostname not in hosts or p.port not in (None, 443) or p.username or p.password:
        raise ValueError("FEC acquisition requires an approved, credential-free HTTPS source URL")
    if (
        p.fragment
        or any(ord(c) <= 32 or c == "\\" for c in url)
        or any(x in {".", ".."} for x in unquote(p.path).split("/"))
    ):
        raise ValueError("FEC URL contains ambiguous path or fragment syntax")
    if any(
        k.casefold() in {"api_key", "api-key", "token", "access_token", "authorization"} for k, _ in parse_qsl(p.query)
    ):
        raise ValueError("FEC credentials must be supplied separately, never in a URL")
    return url
