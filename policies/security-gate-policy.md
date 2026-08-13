# Security Gate Policy

Machine-readable intent lives in `.github/workflows/ai-security-scan.yml`;
this file is the human-readable policy it enforces.

| Layer | Tool | PR gate | Nightly gate |
|---|---|---|---|
| 0a. Threat model (baseline) | Threagile | Blocks merge on any untriaged critical/high risk | Same |
| 0b. Threat model (AI-assisted) | STRIDE GPT | Advisory only - never blocks merge | Same |
| 1. Supply chain | ModelScan, Picklescan, Syft | Blocks merge on any code-execution finding | Full repo + registry sweep |
| 1b. SAST | Semgrep (AI/ML ruleset) | Blocks merge on ERROR severity | Same, plus p/security-audit |
| 1c. Vulnerability scan | Trivy | Blocks merge on any CRITICAL/HIGH finding with a known fix | Same |
| 1d. Dependency CVEs | OSV-Scanner | Blocks merge on any CRITICAL/HIGH finding | Same |
| 2. Data/secrets | detect-secrets | Blocks merge on any hit | Same |
| 3. Red team | Garak (fast subset), Promptfoo | Non-blocking warning on PR; ≥95% pass-rate required to merge to main | Full Garak probe suite, hard-blocking |
| 4. Guardrails | NeMo Guardrails config validation | Blocks merge if config fails to load | Same |

## Why Threagile blocks and STRIDE GPT doesn't
Threagile is a deterministic rule engine over a version-controlled YAML
model - the same input always produces the same output, so it's safe to use
as a hard gate the same way ModelScan or Semgrep is. STRIDE GPT is an
LLM-driven agent - genuinely useful for surfacing threats a static rule
engine won't think of, but non-deterministic and not something a merge
should hinge on. Its findings are advisory: reviewed by the threat-modeler
subagent or a human, and promoted into a permanent Promptfoo test case,
Semgrep rule, or guardrail rail (at which point they're enforced by a
deterministic layer) rather than blocking the build directly.

Trivy and OSV-Scanner block on the same logic as Threagile: both are
deterministic scanners against known-CVE databases (the OS/language package
advisory feeds Trivy uses, and OSV.dev for OSV-Scanner) - same input,
same output, safe to hard-gate. `ignore-unfixed: true` on both keeps the
gate from blocking on CVEs with no available patch yet; those still show
up in the report for tracking, they just don't fail the build.

## Exceptions
Any exception to a blocking gate requires:
1. A written justification in the PR description.
2. Sign-off from the AI Security Platform owner (see Playbook, Roles section).
3. A tracked follow-up issue with a due date.
4. For Trivy/OSV-Scanner specifically, the exception is also recorded as a
   `[[IgnoredVulns]]` entry in `configs/osv-scanner/osv-scanner.toml` (or a
   `.trivyignore` entry) so the suppression is version-controlled, not just
   a one-time manual override.

No exception may be granted for a supply-chain finding that indicates
arbitrary code execution (ModelScan/Picklescan CRITICAL).
