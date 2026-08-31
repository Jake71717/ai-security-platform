#!/usr/bin/env python3
"""
Fail CI if detect-secrets found any potential secrets, and print exactly
what it found (file, line, detector type) so this is diagnosable straight
from the Actions log - not just a bare count that forces a trip to the
downloaded artifact.

Never prints the actual secret value: detect-secrets' own JSON report only
ever stores a hash of the matched text (see "hashed_secret" below), so
there's nothing sensitive to redact here in the first place.

Usage: python3 check_secrets_report.py path/to/secrets-report.json
"""
import json
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: check_secrets_report.py <secrets-report.json>")
        sys.exit(2)

    path = sys.argv[1]
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {path} not found - did the detect-secrets scan step run?")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: could not parse {path} as JSON: {e}")
        sys.exit(1)

    results = data.get("results", {})
    total = sum(len(findings) for findings in results.values())

    if not total:
        print("No potential secrets found. Gate passed.")
        sys.exit(0)

    print(f"BLOCKING - detect-secrets found {total} potential secret(s):\n")
    for filename, findings in results.items():
        for finding in findings:
            line = finding.get("line_number", "?")
            kind = finding.get("type", "unknown type")
            print(f"  - {filename}:{line}  [{kind}]")

    print(
        "\nIf any of these are real credentials: rotate them immediately, then "
        "remove them from the file (and from git history if already pushed).\n"
        "If a finding is a false positive (a test fixture, an example key in "
        "docs, etc.), add an inline `# pragma: allowlist secret` comment on "
        "that line, or maintain a .secrets.baseline via `detect-secrets audit` "
        "- don't just delete this check."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
