"""Apply a source's bounded byte parser or explicitly selected stream parser."""

from spicy_docs.releases.format import SourceNativeReleaseError


def parse_evidence(
    profile, *, opener, evidence_ref, byte_size, media_type, request_key, query_scope, response_bytes=None
):
    if byte_size > profile.max_evidence_bytes:
        raise SourceNativeReleaseError("acquisition evidence exceeds its product bound")
    if profile.parse_page_stream is not None:
        with opener() as stream:
            response = profile.parse_page_stream(
                stream,
                query_scope=query_scope,
                request_key=request_key,
                evidence_ref=evidence_ref,
                byte_size=byte_size,
                media_type=media_type,
            )
        return response, None
    if response_bytes is None:
        with opener() as stream:
            response_bytes = stream.read(profile.max_evidence_bytes + 1)
        if len(response_bytes) > profile.max_evidence_bytes:
            raise SourceNativeReleaseError("acquisition evidence exceeds its product bound")
    return profile.parse_page_response(response_bytes), response_bytes
