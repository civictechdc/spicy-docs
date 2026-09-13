"""GovInfo source metadata, available without acquisition dependencies."""

from .mods import GovInfoModsError, GovInfoModsPackage, ModsElement, ModsRecord, parse_govinfo_mods

__all__ = [
    "GovInfoModsError",
    "GovInfoModsPackage",
    "ModsElement",
    "ModsRecord",
    "parse_govinfo_mods",
]
