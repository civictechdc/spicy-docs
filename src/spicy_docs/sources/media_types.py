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
            "json": "application/json",
            "xhtml": "application/xhtml+xml",
            "csv": "text/csv",
            "ics": "text/calendar",
            "fec": "text/plain",
            "zip": "application/zip",
            "gz": "application/gzip",
            "bz2": "application/x-bzip2",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "mp3": "audio/mpeg",
            "mp4": "video/mp4",
        }
        if normalized in aliases:
            return aliases[normalized]
    suffix = locator.rsplit("?", 1)[0].rsplit(".", 1)[-1].lower()
    if suffix and suffix != locator.lower():
        return media_type(suffix, "")
    return "application/octet-stream"
