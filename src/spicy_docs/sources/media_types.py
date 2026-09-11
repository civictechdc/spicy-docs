"""Media types stated by publishers, with a deterministic extension fallback."""


def media_type(value: object, locator: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if "/" in normalized:
            return normalized
        aliases = {
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "htm": "text/html",
            "html": "text/html",
            "pdf": "application/pdf",
            "txt": "text/plain",
            "xml": "application/xml",
        }
        if normalized in aliases:
            return aliases[normalized]
    suffix = locator.rsplit("?", 1)[0].rsplit(".", 1)[-1].lower()
    if suffix and suffix != locator.lower():
        return media_type(suffix, "")
    return "application/octet-stream"
