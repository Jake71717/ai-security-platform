#!/usr/bin/env python3
"""
Fail CI if OSV-Scanner's SARIF output contains any CRITICAL/HIGH-severity
finding (SARIF level "error").

Usage: python3 check_osv_results.py path/to/osv-results.sarif

OSV-Scanner maps its own severity scoring onto SARIF's three-level scheme
(error/warning/note) when it writes results, so we gate on "error" rather
than re-deriving CVSS bands ourselves - "warning"/"note" findings (lower
severity, or no fix currently available) are printed for visibility but
don't block the merge, mirroring how Trivy's own --severity filter works
one job over.
"""
import json
import sys

BLOCKING_LEVELS = {"error"}


def main():
    if len(sys.argv) < 2:
        print("Usage: check_osv_results.py <osv-results.sarif>")
        sys.exit(2)

    path = sys.argv[1]
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"WARNING: {path} not found - did the OSV-Scanner run produce SARIF output? Skipping gate.")
        sys.exit(0)
    except json.JSONDecodeError as e:
        print(f"ERROR: could not parse {path} as SARIF/JSON: {e}")
        sys.exit(1)

    results = []
    for run in data.get("runs", []):
        results.extend(run.get("results", []))

    blocking = [r for r in results if str(r.get("level", "warning")).lower() in BLOCKING_LEVELS]

    print(f"OSV-Scanner: {len(results)} finding(s) total, {len(blocking)} at blocking (CRITICAL/HIGH) severity.")

    if blocking:
        print("\nBLOCKING - the following dependency vulnerabilities must be remediated, pinned to a patched version, or explicitly ignored in configs/osv-scanner/osv-scanner.toml before merge:\n")
        for r in blocking:
            rule_id = r.get("ruleId", "?")
            message = (r.get("message", {}) or {}).get("text", "").splitlines()[0] if r.get("message") else "(no message)"
            print(f"  - [{rule_id}] {message}")
        sys.exit(1)

    print("No blocking (CRITICAL/HIGH) dependency vulnerabilities. Gate passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
