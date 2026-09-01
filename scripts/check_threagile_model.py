#!/usr/bin/env python3
"""
Structurally validate the Threagile model file *before* it reaches the
`threagile/threagile` container in CI (or a `docker run` on someone's laptop).

Threagile only reports a model error once the image has been pulled and run,
and its message points at a line number without much context. This check runs
in well under a second with no Docker, so a bad enum value, a broken
communication-link target, or a dangling data-asset reference fails fast -
locally as a pre-commit hook (see .pre-commit-config.yaml) and as the first
step of the Layer 0a job.

Three passes:
  1. JSON Schema (draft-07) validation against Threagile's own schema, vendored
     at configs/threagile/schema.json - catches bad enum values, wrong types,
     and missing required keys.
  2. Report constraints the schema can't express: the model `title` becomes the
     Excel worksheet name verbatim, so it must be <=31 chars and free of the
     characters Excel forbids there (colon, backslash, slash, question mark,
     asterisk, square brackets).
  3. Cross-reference checks the schema can't express: communication-link
     targets, data-asset id references, trust-boundary membership, duplicate
     ids, and in-scope assets that sit outside every trust boundary.

This is NOT a substitute for a real Threagile run: it does not evaluate risk
rules or produce risks.json. check_threagile_risks.py still gates on that.

The vendored schema tracks Threagile's master branch, which can be slightly
ahead of the pinned image. If this check and the real tool ever disagree,
the real tool wins - refresh configs/threagile/schema.json from
https://raw.githubusercontent.com/Threagile/threagile/master/support/schema.json

Usage: python3 check_threagile_model.py <model.yaml> [schema.json]
       (schema.json defaults to configs/threagile/schema.json)
"""
import json
import sys
from pathlib import Path

try:
    import yaml
    from jsonschema import Draft7Validator
except ImportError as e:
    print(
        f"ERROR: missing dependency ({e.name}). This check needs PyYAML and "
        f"jsonschema:\n    pip install pyyaml jsonschema\n"
        f"(the pre-commit hook installs these automatically; see "
        f".pre-commit-config.yaml)"
    )
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPO_ROOT / "configs" / "threagile" / "schema.json"


class _StrDateLoader(yaml.SafeLoader):
    """Threagile's Go parser reads `date:` as a plain string. PyYAML would
    otherwise turn `2026-08-13` into a datetime.date and trip the schema's
    string check, a false positive the real tool never raises."""


_StrDateLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    lambda loader, node: loader.construct_scalar(node),
)


def schema_errors(model, schema):
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(model), key=lambda e: list(e.absolute_path))
    for e in errors:
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        print(f"  SCHEMA  {loc}: {e.message}")
    return len(errors)


# Excel worksheet-name constraints. Threagile writes the risks/tags .xlsx with
# a single worksheet named verbatim after the model `title` (see
# pkg/report/excel.go: `sheetName := parsedModel.Title`), and the excelize
# library rejects names longer than 31 chars or containing any of : \ / ? * [ ].
# Threagile does not truncate or sanitise, so a long title fails the whole run
# with "the sheet name length exceeds the 31 characters limit" - after the
# image has been pulled, which the schema check can't catch.
EXCEL_SHEET_NAME_MAX = 31
EXCEL_SHEET_NAME_FORBIDDEN = set(r':\/?*[]')


def report_constraint_problems(model):
    problems = []
    title = model.get("title")
    if not title:
        problems.append("model has no `title` (Threagile needs one for the Excel report)")
    else:
        if len(title) > EXCEL_SHEET_NAME_MAX:
            problems.append(
                f"`title` is {len(title)} chars; Threagile uses it verbatim as the "
                f"Excel worksheet name, which Excel caps at {EXCEL_SHEET_NAME_MAX}. "
                f"Shorten it: {title!r}"
            )
        bad = sorted(EXCEL_SHEET_NAME_FORBIDDEN & set(title))
        if bad:
            problems.append(
                f"`title` contains character(s) Excel forbids in a worksheet name "
                f"({' '.join(bad)}): {title!r}"
            )
    for p in problems:
        print(f"  REPORT  {p}")
    return len(problems)


def xref_problems(model):
    problems = []
    tech = model.get("technical_assets") or {}
    data = model.get("data_assets") or {}
    boundaries = model.get("trust_boundaries") or {}

    tech_ids = {}
    for name, a in tech.items():
        aid = (a or {}).get("id")
        if not aid:
            problems.append(f"technical_asset '{name}' has no id")
            continue
        if aid in tech_ids:
            problems.append(f"duplicate technical_asset id '{aid}' ('{tech_ids[aid]}' and '{name}')")
        tech_ids[aid] = name

    data_ids = {}
    for name, d in data.items():
        did = (d or {}).get("id")
        if not did:
            problems.append(f"data_asset '{name}' has no id")
            continue
        if did in data_ids:
            problems.append(f"duplicate data_asset id '{did}' ('{data_ids[did]}' and '{name}')")
        data_ids[did] = name

    def check_data_refs(where, ids):
        for ref in ids or []:
            if ref not in data_ids:
                problems.append(f"{where}: references unknown data_asset id '{ref}'")

    for name, a in tech.items():
        a = a or {}
        check_data_refs(f"technical_asset '{name}'.data_assets_processed", a.get("data_assets_processed"))
        check_data_refs(f"technical_asset '{name}'.data_assets_stored", a.get("data_assets_stored"))
        for lname, link in (a.get("communication_links") or {}).items():
            link = link or {}
            target = link.get("target")
            if target not in tech_ids:
                problems.append(
                    f"technical_asset '{name}' link '{lname}': target '{target}' "
                    f"is not a known technical_asset id"
                )
            check_data_refs(f"technical_asset '{name}' link '{lname}'.data_assets_sent", link.get("data_assets_sent"))
            check_data_refs(f"technical_asset '{name}' link '{lname}'.data_assets_received", link.get("data_assets_received"))

    boundary_ids = {(b or {}).get("id") for b in boundaries.values()}
    for name, b in boundaries.items():
        b = b or {}
        for ref in b.get("technical_assets_inside") or []:
            if ref not in tech_ids:
                problems.append(f"trust_boundary '{name}'.technical_assets_inside: unknown technical_asset id '{ref}'")
        for ref in b.get("trust_boundaries_nested") or []:
            if ref not in boundary_ids:
                problems.append(f"trust_boundary '{name}'.trust_boundaries_nested: unknown trust_boundary id '{ref}'")

    inside = set()
    for b in boundaries.values():
        inside.update((b or {}).get("technical_assets_inside") or [])
    for aid, name in tech_ids.items():
        if (tech.get(name) or {}).get("out_of_scope"):
            continue
        if aid not in inside:
            problems.append(
                f"technical_asset '{name}' ({aid}) is in scope but not inside any "
                f"trust_boundary (Threagile emits a warning for this)"
            )

    for p in problems:
        print(f"  XREF    {p}")
    return len(problems)


def main():
    if len(sys.argv) < 2:
        print("Usage: check_threagile_model.py <model.yaml> [schema.json]")
        sys.exit(2)

    model_path = sys.argv[1]
    schema_path = sys.argv[2] if len(sys.argv) > 2 else str(DEFAULT_SCHEMA)

    try:
        with open(model_path) as f:
            model = yaml.load(f, Loader=_StrDateLoader)
    except FileNotFoundError:
        print(f"ERROR: {model_path} not found.")
        sys.exit(2)
    except yaml.YAMLError as e:
        print(f"BLOCKING - {model_path} is not valid YAML:\n{e}")
        sys.exit(1)

    try:
        with open(schema_path) as f:
            schema = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: could not load schema {schema_path}: {e}")
        sys.exit(2)

    print(f"Model:  {model_path}")
    print(f"Schema: {schema_path} ({schema.get('id')})\n")

    n_schema = schema_errors(model, schema)
    n_report = report_constraint_problems(model)
    n_xref = xref_problems(model)

    print()
    print(f"Schema errors:        {n_schema}")
    print(f"Report constraints:   {n_report}")
    print(f"Cross-ref problems:   {n_xref}")

    if n_schema or n_report or n_xref:
        print(
            f"\nBLOCKING - fix the issues above in {model_path}. Enum values must "
            f"match Threagile's schema exactly (configs/threagile/schema.json is "
            f"importable into your IDE for autocomplete). This runs before the "
            f"Threagile container so the container never sees a malformed model."
        )
        sys.exit(1)

    print("\nModel is structurally valid. Gate passed (advisory - not a full Threagile run).")
    sys.exit(0)


if __name__ == "__main__":
    main()
