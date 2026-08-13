# AI Security Platform — GitHub Implementation Guide

Step-by-step instructions to stand up the AI Security Platform on GitHub, using the files already in this repository. Read this alongside `AI-Security-Architecture.docx` (the why) and `AI-Security-Playbook.docx` (day-2 operations); this document is the how.

Estimated time: 60–90 minutes for a working pipeline; add 30–60 minutes if you're also standing up the runtime guardrail proxy.

---

## Prerequisites

- A GitHub account or organization with permission to create repositories and configure Actions/branch protection.
- GitHub Actions enabled for the repo (default for personal accounts; org admins may need to allow it under **Settings → Actions → General**).
- An OpenAI and/or Anthropic API key if you want Garak/Promptfoo to test against a hosted model. (You can point them at a self-hosted/Hugging Face endpoint instead — see Step 4.)
- Optional: a Semgrep AppSec Platform account + token, only if you want scan results uploaded there. Not required for the pipeline to function.
- A place to run `docker compose` for the runtime guardrail proxy (a small VM, an existing Docker host, or your laptop for a dev/test pass). Not required just to get CI/CD running.

---

## Step 1 — Create the repository

1. Create a new GitHub repository (or use an existing application repo you want to secure).
2. Copy the contents of this `ai-security-platform/` folder into the repository root — or, if you'd rather keep it separate, into a subfolder (e.g. `security/`) and adjust the paths in `.github/workflows/ai-security-scan.yml` accordingly (the `configs/`, `scripts/`, and `.env.example` references are relative to the repo root by default).
3. Commit and push:
   ```bash
   git init
   git add .
   git commit -m "Add AI Security Platform"
   git branch -M main
   git remote add origin https://github.com/<org>/<repo>.git
   git push -u origin main
   ```

---

## Step 2 — Add repository secrets

The workflow reads three secrets. Go to **Settings → Secrets and variables → Actions → New repository secret** and add whichever apply:

| Secret name | Required? | Notes |
|---|---|---|
| `OPENAI_API_KEY` | Yes, if targeting an OpenAI model | Used by Garak and Promptfoo |
| `ANTHROPIC_API_KEY` | Optional | Only if you add an Anthropic provider to `configs/promptfoo/promptfooconfig.yaml` |
| `SEMGREP_APP_TOKEN` | Optional | Only for uploading results to Semgrep AppSec Platform; the scan runs fine without it |

If you're securing a self-hosted/open-weight model instead of a hosted API, you don't need API key secrets for Garak — change `--model_type openai` to `--model_type huggingface` (or another supported backend) in the workflow, as noted in `configs/garak/README.md`.

> Fork PRs do not receive repository secrets by default. That's intentional — it stops an external contributor's PR from exfiltrating your API keys. It also means Layer 3 (Garak/Promptfoo) will fail on fork PRs; the workflow's `continue-on-error: true` on the PR-fast Garak step absorbs this, but be aware the pass-rate gate will still fail for external contributions unless you set up a maintainer-approval-to-run flow.

---

## Step 3 — Install and test the tools locally (recommended before your first PR)

```bash
cp .env.example .env   # fill in your API keys
./scripts/setup.sh
./scripts/run_local_scan.sh
```

This installs ModelScan, Picklescan, Garak, Promptfoo, NeMo Guardrails, and detect-secrets, and runs a lightweight pass of all four layers against your current repo state. Fix anything obviously broken (missing model files, malformed YAML) before you push — it's much faster to iterate locally than to debug through Actions logs.

---

## Step 4 — Understand and customize the workflow

The pipeline lives at `.github/workflows/ai-security-scan.yml` and is ready to run as-is. Before your first real PR, review and adjust:

1. **Model target** — `red-team-scan` currently points Garak/Promptfoo at `openai:gpt-4o-mini`. Change `--model_name` / the `providers:` block in `configs/promptfoo/promptfooconfig.yaml` to match what you're actually shipping.
2. **Promptfoo test cases** — `configs/promptfoo/promptfooconfig.yaml` ships with a generic customer-support example (`prompts/system-under-test.txt`). Replace the prompt and `tests:`/`redteam.purpose` with your actual application's system prompt and attack surface. Generic test cases catch generic problems; the value of this layer comes from application-specific cases.
3. **Semgrep ruleset** — `configs/semgrep/ai-ml-rules.yml` has four starter rules (unsafe pickle/torch loads, hardcoded keys, unvalidated LLM-output-to-exec, prompt string concatenation). Add rules specific to your framework (LangChain, LlamaIndex, custom agent loop) as you find issues worth codifying.
4. **Pass-rate threshold** — `scripts/check-eval-threshold.js` defaults to 95%. Adjust the second argument in the workflow's "Enforce pass-rate gate" step if that's not the right bar for your maturity level (start lower, ratchet up).

Triggers already configured: every PR to `main`, every push to `main`, and nightly at 03:00 UTC (`workflow_dispatch` is also enabled for manual runs).

---

## Step 4.5 — Set up Layer 0 (automated threat modeling)

Two new jobs run before every other layer: `threat-model-baseline` (Threagile, deterministic, blocking) and `threat-model-ai-assist` (STRIDE GPT, AI-assisted, advisory). Both need one-time setup:

1. **Threagile** runs via Docker (`docker run --rm ... threagile/threagile`), so hosted runners need Docker available — `ubuntu-latest` GitHub-hosted runners have it pre-installed, no action needed. If you use self-hosted runners, confirm Docker is installed.
2. Review `configs/threagile/threagile.yaml` — it ships modeling the *platform's own* reference architecture (client → guardrails proxy → core model, RAG store, model registry, CI/CD runner, Langfuse). **Replace this with your actual system's architecture** before trusting its output: technical assets, data assets, trust boundaries, and communication links all need to reflect what you actually run. The comments at the top of the file link to the official schema for IDE autocomplete.
3. The blocking gate is enforced by `scripts/check_threagile_risks.py`, which fails the build on any critical/high risk that hasn't been triaged. Triage means adding an entry under `risk_tracking:` in the YAML with a status of `mitigated`, `accepted` (with justification), or `false-positive` — leaving something `unchecked` is what blocks the merge.
4. **STRIDE GPT** needs `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (already set up in Step 2 — no new secret required) and analyzes the actual repo contents via an agentic codebase walk, so expect it to take longer and cost more per run than the other jobs. It's intentionally `continue-on-error: true` and excluded from the `security-gate` dependency list — a finding here doesn't block anyone, it's a prompt for a human (or the `threat-modeler` subagent) to review and decide whether to promote it into a permanent test case or guardrail rail.
5. STRIDE GPT's SARIF output is uploaded to **GitHub code scanning** automatically (`github/codeql-action/upload-sarif@v3`), so findings also show up under the repo's **Security → Code scanning alerts** tab, not just as a downloadable artifact.

## Step 4.6 — Set up Layer 1c/1d (Trivy + OSV-Scanner)

Two more jobs run alongside the rest of Layer 1: `trivy-scan` (filesystem/dependency/IaC CVEs and misconfigurations) and `osv-scan` (dependency CVEs via the OSV.dev database). Both are deterministic scanners, so both are hard-blocking, same as ModelScan and Semgrep — no new secrets required for either.

1. **Trivy** installs itself in-job via the official `aquasecurity/trivy-action`, so there's no pre-install step on GitHub-hosted runners. It scans against `configs/trivy/trivy.yaml` (skip-dirs and the `ignore-unfixed` setting) plus the `--severity CRITICAL,HIGH` flag set directly in the workflow.
2. **OSV-Scanner** runs via `docker run ghcr.io/google/osv-scanner` — same pattern as Threagile, so the Docker prerequisite from Step 4.5 covers this too. Its SARIF output is checked by `scripts/check_osv_results.py`, which fails the build on any SARIF `error`-level (CRITICAL/HIGH) result.
3. Both jobs upload their SARIF to **GitHub code scanning** (`github/codeql-action/upload-sarif@v3`), so findings land in **Security → Code scanning alerts** alongside STRIDE GPT and Semgrep's results.
4. To accept a specific finding rather than fix it: add a `[[IgnoredVulns]]` block with a reason to `configs/osv-scanner/osv-scanner.toml` for OSV-Scanner, or a `.trivyignore` file at the repo root for Trivy. Undocumented suppressions aren't supported by either tool's CLI flags used here — the point is to force a paper trail, same as Threagile's `risk_tracking:`.
5. Both scanners flag against the *current* repo contents, so on a brand-new repo with no dependencies yet, expect both jobs to pass instantly with zero findings — that's expected, not a misconfiguration.

## Step 5 — Require the Security Gate on protected branches

1. Go to **Settings → Branches → Add branch protection rule** (or **Add rule** if one exists for `main`).
2. Under **Require status checks to pass before merging**, search for and select:
   - `Security Gate (aggregate)` (the job named `security-gate`)
3. You do **not** need to individually require the other five jobs — `security-gate` already depends on all of them and fails if any one does, so requiring just it is sufficient and keeps the branch-protection UI simpler.
4. Enable **Require branches to be up to date before merging** so the gate always runs against the latest `main`.
5. Save.

From this point, no PR can merge to `main` without passing all four layers.

---

## Step 6 — Open a test PR to validate the pipeline end-to-end

1. Create a branch, make a trivial change (e.g. edit `README.md`), and open a PR.
2. Watch the **Checks** tab — you should see six jobs run: `supply-chain-scan`, `sast-scan`, `data-pipeline-scan`, `red-team-scan`, `guardrails-validate`, and `security-gate`.
3. Confirm `security-gate` goes green only after the other five finish, and that it's listed as a required check blocking merge until it does.
4. Deliberately break something to confirm the gate actually blocks — e.g. temporarily hardcode a fake API key (`sk-test1234567890abcdefghij`) in a scratch file and push it. `data-pipeline-scan` should fail and `security-gate` should block the merge button. Revert the change afterward.

---

## Step 7 — Deploy the runtime guardrail proxy (Layer 4)

This is separate from CI/CD — it's the always-on proxy that sits in front of your production model.

1. Provision a small host with Docker installed (a $5–10/mo VM is plenty for NeMo Guardrails + Langfuse at low-to-moderate traffic; scale up as needed).
2. Copy `docker-compose.guardrails.yml`, `.env.example` (renamed `.env` with real values), and `configs/nemo-guardrails/` to the host.
3. Start it:
   ```bash
   docker compose -f docker-compose.guardrails.yml up -d
   ```
4. Point your application at `http://<host>:8001` instead of calling the model provider directly. The proxy forwards through NeMo Guardrails' input/output rails before/after hitting the actual model.
5. Open Langfuse at `http://<host>:3001` and confirm traces are showing up as you send test traffic.
6. Consider fronting this with a reverse proxy / TLS termination (Caddy, nginx, or your cloud provider's load balancer) before sending real production traffic — the compose file as shipped is HTTP-only for simplicity.

For a managed alternative, you can run just the `guardrails-proxy` service on any container platform (ECS, Cloud Run, Azure Container Apps, Fly.io) — it only needs the `configs/nemo-guardrails` volume mounted and the two API key env vars.

---

## Step 8 — Wire up agents and the MCP server (optional but recommended)

1. Copy `agents/*.md` into your project's `.claude/agents/` directory to make the four subagents (`supply-chain-scanner`, `red-team-agent`, `guardrails-auditor`, `incident-responder`) available in Claude Code or any Claude Agent SDK-based workflow.
2. Register the MCP server so an agent can call the scanners directly instead of shelling out blind:
   ```bash
   pip install mcp
   ```
   Add `mcp/mcp.config.json`'s contents to your MCP client's config (Claude Code's `.mcp.json`, Claude Desktop's config, or Cowork's connector settings).
3. Test it: ask an agent to "scan the model weights in this repo" or "run a Garak probe against gpt-4o-mini" and confirm it calls the tool rather than trying to shell out on its own.

---

## Step 9 — Confirm the nightly schedule and set artifact retention

1. GitHub Actions schedules can drift or silently stop firing on inactive repos — after 24–48 hours, check **Actions → AI Security Platform - Full Scan** for a run triggered by `schedule` (not `pull_request`/`push`).
2. Go to **Settings → Actions → General → Artifact and log retention** and set a retention period that matches your audit/compliance needs (default is 90 days). The `red-team-reports`, `supply-chain-reports`, and `data-pipeline-report` artifacts are your evidence trail for Playbook Section 5.2 (Preserve evidence).

---

## Step 10 — Ongoing operation

Hand off to the **AI Security Playbook**:

- Section 3 (Per-Layer Runbooks) for how to run and interpret each scanner day-to-day.
- Section 5 (Incident Response) for what to do when a scan or the runtime proxy catches something real.
- Section 6 (Maintenance Cadence) for weekly/monthly/quarterly upkeep — including re-checking tool status, since this space moves fast (see the Architecture Document's status notes on Promptfoo/ModelScan ownership changes).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `security-gate` shows as skipped, not failed | You required the individual layer jobs instead of `security-gate` in branch protection, or a dependency job was cancelled rather than failed. Re-check Step 5. |
| Garak/Promptfoo steps fail with auth errors | Secret not set, or set at the wrong scope (repo vs. environment vs. org). Re-check Step 2; also confirm the PR is not from a fork. |
| `pip install` steps fail intermittently on hosted runners | Transient PyPI/network issue — re-run the job. If persistent, pin tool versions in the workflow instead of installing `latest`. |
| Semgrep step fails immediately with a token error | `SEMGREP_APP_TOKEN` is optional — if you don't have one, remove the `env:` line referencing it rather than leaving it unset; some Semgrep CLI versions treat an empty token differently from a missing one. |
| `modelscan`/`picklescan` step is a no-op | Expected if your repo doesn't commit model weight files directly (e.g. you pull them from Hugging Face/S3 at deploy time). Add a step that downloads the artifact before scanning if you want CI-time coverage of externally-hosted weights. |
| Nightly run never fires | Confirm the workflow file is on the default branch — GitHub only evaluates `schedule` triggers from the file as it exists on the repo's default branch, not from feature branches. |
| `threat-model-baseline` fails immediately, no risks.json | Threagile's exact output filenames/paths can shift between versions — run it locally first (`docker run --rm -v "$(pwd)/configs/threagile:/app/work" threagile/threagile -model /app/work/threagile.yaml -output /app/work/output`) and confirm what it actually writes to `output/`, then adjust `scripts/check_threagile_risks.py`'s input path if needed. |
| `threat-model-ai-assist` never seems to block anything, even on obvious findings | Working as designed — it's advisory only (see Step 4.5). If you want it blocking, remove `continue-on-error: true` and add the job to `security-gate`'s `needs:` list, but be aware this makes your merge gate depend on a non-deterministic LLM call. |
| `trivy-scan` fails on every run, even on a brand-new repo | Check `--severity` and `--ignore-unfixed` are actually being passed (they're set via the `trivy-action` inputs, not `configs/trivy/trivy.yaml`) — a stale local edit to only the YAML won't change CLI-level flags. |
| `osv-scan` job hangs or times out | The Docker pull of `ghcr.io/google/osv-scanner` can be slow on the first run on a given runner; re-run once cached, or pin a specific tag instead of `:latest` to get a smaller, more predictable image. |
