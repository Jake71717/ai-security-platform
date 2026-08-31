#!/usr/bin/env python3
"""
Fail CI if Threagile found any critical/high risk that hasn't been triaged
in risk_tracking (i.e. still "unchecked").

Usage: python3 check_threagile_risks.py path/to/risks.json

Threagile's exact JSON export layout has shifted across versions, so this
parser is defensive: it recursively walks the document looking for objects
that look like a risk entry (has a "severity" key) rather than assuming one
fixed schema. Verify this against your installed Threagile version's actual
output once and adjust BLOCKING_SEVERITIES / the "unchecked" status check
below if your version's field names differ.
"""
import json
import sys

BLOCKING_SEVERITIES = {"critical", "high"}
# Statuses that mean a human has already looked at this risk and made a call.
TRIAGED_STATUSES = {"accepted", "in-progress", "mitigated", "false-positive"}


def find_risk_entries(node, found):
    if isinstance(node, dict):
        if "severity" in node and isinstance(node.get("severity"), str):
            found.append(node)
        for v in node.values():
            find_risk_entries(v, found)
    elif isinstance(node, list):
        for item in node:
            find_risk_entries(item, found)


def main():
    if len(sys.argv) < 2:
        print("Usage: check_threagile_risks.py <risks.json>")
        sys.exit(2)

    path = sys.argv[1]
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        # This is a BLOCKING gate ("deterministic, blocking" per the workflow
        # comment) - a missing risks.json means Threagile didn't actually run
        # (e.g. a container permission error, a changed CLI flag, etc.), not
        # that there are zero risks. Failing open here would let any change
        # that silently breaks the Threagile step sail through as "passed".
        print(f"ERROR: {path} not found - the Threagile run did not produce a risk export. "
              f"Treating this as a failed gate rather than skipping it.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: could not parse {path} as JSON: {e}")
        sys.exit(1)

    risks = []
    find_risk_entries(data, risks)

    blocking = []
    for r in risks:
        severity = str(r.get("severity", "")).lower()
        status = str(r.get("status") or r.get("risk_status") or "unchecked").lower()
        if severity in BLOCKING_SEVERITIES and status not in TRIAGED_STATUSES:
            blocking.append(r)

    print(f"Threagile: {len(risks)} risk entries found, {len(blocking)} untriaged at critical/high severity.")

    if blocking:
        print("\nBLOCKING - the following risks must be triaged (mitigated, accepted with justification, or marked false-positive in risk_tracking) before merge:\n")
        for r in blocking:
            title = r.get("title") or r.get("category") or r.get("id") or "(untitled risk)"
            asset = r.get("most_relevant_technical_asset") or r.get("technical_asset") or "?"
            print(f"  - [{r.get('severity')}] {title} @ {asset}")
        sys.exit(1)

    print("No untriaged critical/high risks. Gate passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
