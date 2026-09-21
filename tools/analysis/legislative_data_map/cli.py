"""Measure the legislative-branch data map: what each route lists, from when, and how big.

One bounded pass over three machine-readable inventories plus a fixed set of
publisher samples, then the map's tables are rewritten from those measurements
and the judgments held in ``ROWS`` below. Judgments (status, note) are data
here so that a status can never cite a module that does not exist: every
``have`` and ``port`` row names evidence paths and the run refuses if one is
missing. Run from the repository root:

  uv run --frozen python -m tools.analysis.legislative_data_map \\
      --env-file .env --output docs/research/legislative-data-map-2026-09-18.json \\
      --map docs/research/legislative-data-map-2026-09-18.md

``--offline`` refreshes the tables and saved row judgments from an existing
output without changing its measurements or using the network.

Measurements, and what each cannot see:

* Congress.gov: one ``limit=1`` request per collection route for its declared
  total, then a descent by Congress (or volume) until two empty Congresses
  follow a populated one, or the cap. The earliest populated Congress is a
  lower bound on coverage; a gap wider than one Congress would hide older
  material and the cap is reported when it ends the walk.
* GovInfo: the ``collections`` inventory for package counts; for named
  collections a binary search on ``published/{year}-01-01`` for the earliest
  issue year, checked against the inventory count; the keyless bulkdata
  listing for folder ranges and top-level sizes.
* The CDTF catalog for periodicity and the caveat counts.
* One keyless sample per publisher XML or JSON candidate: media type, size,
  digest, root element and first-level children. Whether those name the
  document's own identity remains a judgment in the row note.

A credential refusal (401/403 on a keyed route) aborts the run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.congress.listing import CongressListingReader
from spicy_docs.sources.govinfo.discovery import GovInfoDiscoveryReader
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential
from tools.analysis.legislative_data_map.capture import (
    measure_catalog,
    measure_congress,
    measure_govinfo,
    measure_latest,
    measure_samples,
)
from tools.analysis.legislative_data_map.comparisons import measure_comparisons
from tools.analysis.legislative_data_map.floors import measure_edge_samples, measure_floors, measure_requirements
from tools.analysis.legislative_data_map.flow import measure_flow
from tools.analysis.legislative_data_map.rows import CONGRESS_ROUTES, ROWS
from tools.analysis.legislative_data_map.tables import (
    _revision,
    check_evidence,
    diff_measures,
    render_tables,
    rewrite_map,
)
from tools.analysis.shared import REQUESTS, KeylessProbe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output", type=Path, required=True, help="measurements JSON; read instead of measured with --offline"
    )
    parser.add_argument("--map", type=Path, required=True, help="the markdown map whose generated tables are rewritten")
    parser.add_argument("--env-file", type=Path, help="file holding the api.data.gov key")
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--compare", action="store_true", help="run only the comparisons and merge them into --output")
    parser.add_argument(
        "--samples", action="store_true", help="re-sample only the publisher files and merge into --output"
    )
    parser.add_argument(
        "--flow", action="store_true", help="run only the data-flow edge probes and merge into --output"
    )
    parser.add_argument("--freshness", action="store_true", help="re-measure only each route's newest update date")
    parser.add_argument(
        "--floors", action="store_true", help="continue each route's descent past its recorded coverage floor"
    )
    parser.add_argument(
        "--requirements",
        action="store_true",
        help="walk house-requirement 8070's matching-communications once and probe its detail floor",
    )
    parser.add_argument("--sample", type=int, default=0, help="with --flow: also follow each edge from this many items")
    parser.add_argument("--diff", type=Path, help="print what moved since this earlier output file")
    parser.add_argument("--max-descent", type=int, default=60, help="requests per route when walking back by Congress")
    parser.add_argument("--min-interval-seconds", type=float, default=0.3)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    check_evidence(root)
    if args.offline:
        measures = json.loads(args.output.read_text())
    elif args.floors:
        if args.env_file is None:
            parser.error("--env-file is required for --floors")
        api_key = read_api_key(args.env_file, args.env_var)
        budget = PagedJsonBudget(
            max_requests=3,
            max_page_bytes=4 * 1024 * 1024,
            timeout_seconds=args.timeout,
            min_request_interval_seconds=args.min_interval_seconds,
        )
        measures = json.loads(args.output.read_text())
        with CongressListingReader(budget=budget, api_key=api_key) as congress:
            measure_floors(congress, measures, api_key)
        measures["floorsRequests"] = dict(REQUESTS)
        measures["floorsAt"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    elif args.requirements:
        if args.env_file is None:
            parser.error("--env-file is required for --requirements")
        api_key = read_api_key(args.env_file, args.env_var)
        budget = PagedJsonBudget(
            max_requests=3,
            max_page_bytes=4 * 1024 * 1024,
            timeout_seconds=args.timeout,
            min_request_interval_seconds=args.min_interval_seconds,
        )
        measures = json.loads(args.output.read_text())
        with CongressListingReader(budget=budget, api_key=api_key) as congress:
            measures["requirements"] = measure_requirements(congress, api_key)
        measures["requirementsRequests"] = dict(REQUESTS)
        measures["requirementsAt"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    elif args.freshness:
        if args.env_file is None:
            parser.error("--env-file is required for --freshness")
        api_key = read_api_key(args.env_file, args.env_var)
        budget = PagedJsonBudget(
            max_requests=3,
            max_page_bytes=4 * 1024 * 1024,
            timeout_seconds=args.timeout,
            min_request_interval_seconds=args.min_interval_seconds,
        )
        measures = json.loads(args.output.read_text())
        with CongressListingReader(budget=budget, api_key=api_key) as congress:
            for route in CONGRESS_ROUTES:
                facts = measures.setdefault("congress", {}).setdefault(route.route, {})
                for stale in ("latestUpdate", "latestSortHonored", "latestPath", "latestUpdateError"):
                    facts.pop(stale, None)
                facts.update(measure_latest(congress, route, api_key))
                print(
                    f"freshness {route.route}: {facts.get('latestUpdate')} honored={facts.get('latestSortHonored')}",
                    file=sys.stderr,
                )
        measures["freshnessRequests"] = dict(REQUESTS)
        measures["freshnessAt"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    elif args.samples:
        measures = json.loads(args.output.read_text())
        with KeylessProbe(
            timeout_seconds=args.timeout, min_request_interval_seconds=args.min_interval_seconds
        ) as probe:
            measures["samples"] = measure_samples(probe)
        measures["sampledAt"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    elif args.flow:
        if args.env_file is None:
            parser.error("--env-file is required for --flow")
        api_key = read_api_key(args.env_file, args.env_var)
        budget = PagedJsonBudget(
            max_requests=3,
            max_page_bytes=16 * 1024 * 1024,
            timeout_seconds=args.timeout,
            min_request_interval_seconds=args.min_interval_seconds,
        )
        measures = json.loads(args.output.read_text())
        try:
            with (
                CongressListingReader(budget=budget, api_key=api_key) as congress,
                GovInfoDiscoveryReader(budget=budget, api_key=api_key) as govinfo,
                KeylessProbe(
                    timeout_seconds=args.timeout, min_request_interval_seconds=args.min_interval_seconds
                ) as probe,
            ):
                measures["flow"] = measure_flow(congress, govinfo, probe, api_key)
                if args.sample:
                    measures["flowSamples"] = measure_edge_samples(congress, govinfo, probe, api_key, args.sample)
                    measures["flowSampleSize"] = args.sample
        except CredentialRefusedError as error:
            print(f"credential refused; stopping: {scrub_credential(str(error), api_key)}", file=sys.stderr)
            return 1
        measures["flowRequests"] = dict(REQUESTS)
        measures["flowAt"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    elif args.compare:
        if args.env_file is None:
            parser.error("--env-file is required for --compare")
        api_key = read_api_key(args.env_file, args.env_var)
        budget = PagedJsonBudget(
            max_requests=3,
            max_page_bytes=16 * 1024 * 1024,
            timeout_seconds=args.timeout,
            min_request_interval_seconds=args.min_interval_seconds,
        )
        measures = json.loads(args.output.read_text())
        try:
            with (
                CongressListingReader(budget=budget, api_key=api_key) as congress,
                GovInfoDiscoveryReader(budget=budget, api_key=api_key) as govinfo,
                KeylessProbe(
                    timeout_seconds=args.timeout, min_request_interval_seconds=args.min_interval_seconds
                ) as probe,
            ):
                measures["comparisons"] = measure_comparisons(congress, govinfo, probe, api_key)
        except CredentialRefusedError as error:
            print(f"credential refused; stopping: {scrub_credential(str(error), api_key)}", file=sys.stderr)
            return 1
        measures["compareRequests"] = dict(REQUESTS)
        measures["comparedAt"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    else:
        if args.env_file is None:
            parser.error("--env-file is required unless --offline")
        api_key = read_api_key(args.env_file, args.env_var)
        budget = PagedJsonBudget(
            max_requests=3,
            max_page_bytes=4 * 1024 * 1024,
            timeout_seconds=args.timeout,
            min_request_interval_seconds=args.min_interval_seconds,
        )
        previous = json.loads(args.output.read_text()) if args.output.exists() else {}
        measures: dict[str, Any] = {"generatedAt": datetime.now(UTC).isoformat(), "revision": _revision(root)}
        carried = (
            "comparisons", "compareRequests", "comparedAt", "flow", "flowRequests", "flowAt",
            "flowSamples", "flowSampleSize", "sampledAt", "freshnessAt", "floorsAt",
            "requirements", "requirementsRequests", "requirementsAt",
        )  # fmt: skip
        measures.update({k: previous[k] for k in carried if k in previous})
        try:
            with (
                CongressListingReader(budget=budget, api_key=api_key) as congress,
                GovInfoDiscoveryReader(budget=budget, api_key=api_key) as govinfo,
                KeylessProbe(
                    timeout_seconds=args.timeout, min_request_interval_seconds=args.min_interval_seconds
                ) as probe,
            ):

                def checkpoint() -> None:
                    args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")

                measures["congress"] = measure_congress(congress, max_descent=args.max_descent, api_key=api_key)
                checkpoint()
                measures["govinfo"] = measure_govinfo(govinfo, probe, api_key=api_key)
                checkpoint()
                measures["catalog"] = measure_catalog(probe)
                checkpoint()
                measures["samples"] = measure_samples(probe)
                measures["requests"] = dict(REQUESTS)
        except CredentialRefusedError as error:
            print(f"credential refused; stopping: {scrub_credential(str(error), api_key)}", file=sys.stderr)
            return 1
        measures["requests"]["total"] = sum(measures["requests"].values())
    # Judgments belong to this tree; retain the original measurement dates,
    # revision and request counts when refreshing them offline.
    measures["rows"] = [asdict(row) for row in ROWS]
    args.output.write_text(json.dumps(measures, indent=2, sort_keys=True) + "\n")
    if args.diff:
        print("\n".join(diff_measures(json.loads(args.diff.read_text()), measures)))
    rewrite_map(args.map, render_tables(measures))
    print(json.dumps({"output": str(args.output), "map": str(args.map), "requests": measures.get("requests")}))
    return 0
