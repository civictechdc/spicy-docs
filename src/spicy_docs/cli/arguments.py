"""Argument syntax for the source-native operator commands."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from spicy_docs.cli.sources import PUBLIC_TABLE_CHOICES, SOURCE_CHOICES


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish, verify, or inspect immutable source-native releases and public Parquet tables."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser(
        "publish",
        help="Acquire, publish, and producer-verify one release",
    )
    publish.add_argument("--source", choices=SOURCE_CHOICES, required=True)
    publish.add_argument(
        "--since",
        type=_date,
        help="Start of the source date window; required by every dated source",
    )
    publish.add_argument(
        "--until",
        type=_date,
        help="End of the source date window; required by every dated source",
    )
    publish.add_argument(
        "--agency",
        action="append",
        help="Agency code; repeat for multiple agencies",
    )
    publish.add_argument(
        "--product-id",
        action="append",
        help="Closed GAO product ID; repeat for multiple product pages",
    )
    publish.add_argument("--destination", type=Path, required=True)
    publish.add_argument(
        "--blob-store",
        type=Path,
        required=True,
        help="Explicit persistent content-addressed payload store",
    )
    publish.add_argument("--implementation-id", required=True)

    for command, help_text in (
        ("verify", "Independently replay and verify one immutable release"),
        ("inspect", "Admit one release and report collection outcomes and bounded failure details"),
    ):
        read = subparsers.add_parser(command, help=help_text)
        read.add_argument("--source", choices=SOURCE_CHOICES, required=True)
        read.add_argument("--release", type=Path, required=True)
        read.add_argument(
            "--blob-store",
            type=Path,
            required=True,
            help="Explicit persistent content-addressed payload store",
        )
        read.add_argument("--logical-id", required=True)
        read.add_argument("--artifact-digest", required=True)
        read.add_argument(
            "--accepted-verifier-implementation-id",
            action="append",
            required=True,
        )
        if command == "inspect":
            read.add_argument(
                "--failure-limit",
                type=_nonnegative_int,
                default=20,
                help="Maximum failure rows to report (default: 20; 0 reports only the outcome)",
            )

    publish_public_table = subparsers.add_parser(
        "publish-public-table",
        help="Project one admitted source-native release into one immutable public Parquet table",
    )
    publish_public_table.add_argument("--table", choices=PUBLIC_TABLE_CHOICES, required=True)
    publish_public_table.add_argument(
        "--source-release",
        type=Path,
        required=True,
        help="Root of the admitted source-native release this table projects",
    )
    publish_public_table.add_argument(
        "--source-blob-store",
        type=Path,
        required=True,
        help="Explicit persistent content-addressed payload store for the source-native release",
    )
    publish_public_table.add_argument(
        "--source-accepted-verifier-implementation-id",
        action="append",
        required=True,
        help="Verifier implementation id(s) accepted for the admitted source-native release",
    )
    publish_public_table.add_argument("--destination", type=Path, required=True)
    publish_public_table.add_argument("--implementation-id", required=True)

    verify_public_table = subparsers.add_parser(
        "verify-public-table",
        help="Check the pin, profile, and admission of one immutable public Parquet table",
    )
    verify_public_table.add_argument("--table", choices=PUBLIC_TABLE_CHOICES, required=True)
    verify_public_table.add_argument("--release", type=Path, required=True)
    verify_public_table.add_argument("--logical-id", required=True)
    verify_public_table.add_argument("--artifact-digest", required=True)
    verify_public_table.add_argument(
        "--accepted-verifier-implementation-id",
        action="append",
        required=True,
    )
    return parser
