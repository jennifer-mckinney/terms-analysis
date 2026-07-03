#!/usr/bin/env python3
"""CSV-in / CSV-out helper for the API-only Flow 2 batch endpoint.

Reads a CSV with columns ``name,url,jurisdiction`` (jurisdiction may be blank
for the no-filter contract), calls ``POST /analyze/batch`` in a single request,
and writes a summary CSV with grade, verdict, and finding counts per item.

This is a convenience wrapper, not the contract. The contract is the JSON
endpoint documented in PRD v2.3 §6.2 / §7.3.13. Researchers who need custom
behavior (parallel batches, resume-on-failure, custom output shapes) should
call the endpoint directly with their own client.

Usage:
    python batch_analyze.py --input policies.csv --output results.csv \\
        [--api http://localhost:9000] [--doc-type privacy_policy] \\
        [--industry healthcare] [--context for_work]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

# Reviewer P9 (security F7): bound the response body read. urllib will happily
# stream a hostile / misbehaving server's response into memory without limit,
# which turns a batch helper into an OOM vector when pointed at an untrusted
# API base. 100 MB is well above legitimate batch response sizes.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024

# Non-local API bases are legitimate (remote FastAPI deployment) but warrant a
# stderr warning so a copy-pasted CLI invocation against a random host prompts
# the operator to think about trust before shipping content there.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def read_input_csv(path: Path) -> List[Dict[str, str]]:
    """Read the input CSV into a list of dicts with name/url/jurisdiction."""
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"name", "url", "jurisdiction"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"input CSV missing required columns: {sorted(missing)}")
        return [dict(row) for row in reader]


def build_batch_request(
    rows: List[Dict[str, str]],
    doc_type: str | None,
    industry: str | None,
    context: List[str],
) -> Dict[str, Any]:
    """Assemble the AnalyzeBatchRequest JSON body.

    Empty jurisdictions across all rows -> [] (no-filter contract).
    Mixed jurisdictions -> collect unique non-empty values.
    """
    items = []
    juris_union: List[str] = []
    for row in rows:
        item: Dict[str, Any] = {"name": row["name"], "url": row["url"]}
        if doc_type:
            item["doc_type"] = doc_type
        items.append(item)
        j = (row.get("jurisdiction") or "").strip()
        if j and j not in juris_union:
            juris_union.append(j)

    body: Dict[str, Any] = {
        "items": items,
        "jurisdictions": juris_union,  # empty list preserved = no filter
        "mode": "full",
        "detect_cross_references": True,
        "context": context,
    }
    if industry:
        body["industry"] = industry
    return body


def _warn_if_non_local(api_base: str) -> None:
    """Emit a stderr warning when ``api_base`` points at a non-local host.

    Reviewer P9 (security F7): a local-only tool that will happily POST every
    row of a CSV to an arbitrary URL should say something out loud when that
    URL is not one of the standard loopback hosts.
    """
    try:
        parsed = urllib.parse.urlparse(api_base)
    except (ValueError, TypeError):
        return
    host = (parsed.hostname or "").lower()
    if host and host not in _LOCAL_HOSTS:
        print(
            f"WARNING: --api is not local host: {api_base}. "
            "Continue only if you trust it.",
            file=sys.stderr,
        )


def call_batch_endpoint(api_base: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST the request body to /analyze/batch and return the parsed response.

    The response body is read with a hard cap of ``MAX_RESPONSE_BYTES`` (100 MB).
    Anything larger raises ``ValueError`` before decoding. Reviewer P9
    (security F7) memory-exhaustion guardrail.
    """
    url = api_base.rstrip("/") + "/analyze/batch"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            # Read one byte past the cap so we can detect overflow deterministically.
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeded 100 MB cap")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"network error calling {url}: {exc.reason}") from exc


def write_summary_csv(path: Path, result: Dict[str, Any]) -> None:
    """Flatten each AnalysisPayload to a summary row and write to CSV."""
    fieldnames = [
        "name",
        "url",
        "grade",
        "risk_score",
        "verdict_headline",
        "verdict_label",
        "num_findings",
        "num_high",
        "num_medium",
        "num_low",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for item in result.get("items", []):
            findings = item.get("findings", []) or []
            sev = [f.get("severity", "").lower() for f in findings]
            writer.writerow(
                {
                    "name": item.get("name", ""),
                    "url": item.get("url", ""),
                    "grade": item.get("grade", ""),
                    "risk_score": item.get("risk_score", ""),
                    "verdict_headline": item.get("verdict_headline", ""),
                    "verdict_label": item.get("verdict_label", ""),
                    "num_findings": len(findings),
                    "num_high": sev.count("high"),
                    "num_medium": sev.count("medium"),
                    "num_low": sev.count("low"),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input CSV path")
    parser.add_argument("--output", required=True, type=Path, help="Output CSV path")
    parser.add_argument("--api", default="http://localhost:9000", help="API base URL")
    parser.add_argument("--doc-type", default=None, help="Optional doc_type for all items")
    parser.add_argument("--industry", default=None, help="Optional industry profile")
    parser.add_argument(
        "--context",
        default="",
        help="Comma-separated context chips (e.g. 'for_work,want_understand')",
    )
    args = parser.parse_args()

    # Reviewer P9 F7: warn early (before any file I/O) if --api points
    # somewhere other than a local loopback host.
    _warn_if_non_local(args.api)

    context = [c.strip() for c in args.context.split(",") if c.strip()]
    rows = read_input_csv(args.input)
    if not rows:
        print("input CSV had no data rows; nothing to do", file=sys.stderr)
        return 1

    body = build_batch_request(rows, args.doc_type, args.industry, context)
    result = call_batch_endpoint(args.api, body)
    write_summary_csv(args.output, result)
    print(f"wrote {len(result.get('items', []))} rows to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
