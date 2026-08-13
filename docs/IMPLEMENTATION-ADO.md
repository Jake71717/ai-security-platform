# AI Security Platform — Azure DevOps Implementation Guide

Step-by-step instructions to stand up the AI Security Platform on Azure DevOps (Azure Repos + Azure Pipelines), using `azure-pipelines.yml` in this repository. Read this alongside `AI-Security-Architecture.docx` (the why) and `AI-Security-Playbook.docx` (day-2 operations); this document is the how.

Estimated time: 75–100 minutes for a working pipeline; add 30–60 minutes if you're also standing up the runtime guardrail proxy.

This guide assumes a standard Azure Repos Git + Azure Pipelines setup. If your code lives in **GitHub** but you run **Azure Pipelines** as external CI against it, see the callout at the end of Step 6 — most of this guide still applies, with branch protection moving to GitHub's side.

---

## Prerequisites

- An Azure DevOps organization and project, with permission to create repos, pipelines, variable groups, and branch policies.
- Sufficient parallel jobs / pipeline minutes. Microsoft-hosted agents ship with a free tier for public projects; private projects need either a paid parallelism grant or [a free grant request](https://learn.microsoft.com/en-us/azure/devops/pipelines/licensing/concurrent-jobs) if you've never used Pipelines in this org before. Five jobs run in parallel in this pipeline (`SupplyChainScan`, `SastScan`, `DataPipelineScan`, `RedTeamScan`, `GuardrailsValidate`) plus `SecurityGate` — confirm you have at least 1–2 parallel jobs available, more if you want them to run concurrently rather than queued.
- An OpenAI and/or Anthropic API key if targeting a hosted model.
- Optional: a Semgrep AppSec Platform token.
- A place to run `docker compose` for the runtime guardrail proxy — an Azure VM is the path of least resistance and is what this guide uses; Azure Container Instances is noted as an alternative.

---

## Step 1 — Create the project and push the repository

1. In Azure DevOps, create a new project (or use an existing one).
2. Push this `ai-security-platform/` folder to Azure Repos:
   ```bash
   git init
   git add .
   git commit -m "Add AI Security Platform"
   git branch -M main
   git remote add origin https://dev.azure.com/<org>/<project>/_git/<repo>
   git push -u origin main
   ```
3. Confirm `azure-pipelines.yml` is present at the repo root (or note its path if you moved it — you'll need that path in Step 4).

---

## Step 2 — Create the secrets variable group

Azure Pipelines does not read a `.env` file or repo secrets the way GitHub Actions does — secrets live in a **Library variable group** (or, for stronger controls, an Azure Key Vault-backed variable group).

1. Go to **Pipelines → Library → + Variable group**.
2. Name it exactly `ai-security-platform-secrets` (this matches the `variables: - group:` reference in `azure-pipelines.yml` — rename both together if you change it).
3. Add variables and click the **lock icon** to mark each as secret:
   - `OPENAI_API_KEY`
   - `ANTHROPIC_API_KEY` (optional)
   - `SEMGREP_APP_TOKEN` (optional)
4. Save.

**Stronger option:** instead of typing secrets directly into the variable group, link it to Azure Key Vault (**Variable group → Link secrets from an Azure key vault as variables**, requires an Azure subscription service connection). This is worth doing if you already manage secrets in Key Vault elsewhere — it keeps this pipeline from being a second place credentials can leak from.

---

## Step 3 — Create the pipeline

1. Go to **Pipelines → New pipeline**.
2. Choose **Azure Repos Git**, select your repository.
3. Choose **Existing Azure Pipelines YAML file**, point it at `/azure-pipelines.yml` (adjust the path if you placed the platform in a subfolder).
4. Before saving, click **Variables** (or just proceed — the pipeline references the variable group directly via YAML, so no manual variable entry is needed here) and confirm the pipeline **Save** (not **Run**) so you can grant permissions first (Step 5) before its first execution.

---

## Step 4 — Review and customize the pipeline

`azure-pipelines.yml` is a direct translation of the GitHub Actions workflow, job-for-job. Before your first real run, adjust the same three things called out in the GitHub guide:

1. **Model target** — `RedTeamScan` points Garak/Promptfoo at `openai:gpt-4o-mini` by default; update `--model_name` and `configs/promptfoo/promptfooconfig.yaml`'s `providers:` block for your actual model. For a self-hosted model, change `--model_type openai` to the appropriate backend (`huggingface`, etc.).
2. **Promptfoo test cases** — replace the generic customer-support example in `configs/promptfoo/promptfooconfig.yaml` and `configs/promptfoo/prompts/system-under-test.txt` with your application's real system prompt and attack surface.
3. **Semgrep ruleset** — extend `configs/semgrep/ai-ml-rules.yml` with rules specific to your framework as you find issues worth codifying.

Notable YAML-schema differences from the GitHub version, in case you're comparing the two files side by side:

- `dependsOn` replaces GitHub's `needs:`.
- Secrets come from the linked variable group (`variables: - group: ai-security-platform-secrets`) rather than the `${{ secrets.X }}` syntax — they're referenced the same way (`$(OPENAI_API_KEY)`) once the group is linked.
- The PR-vs-nightly branching in `RedTeamScan` uses `condition: eq(variables['Build.Reason'], 'PullRequest')` / `'Schedule'` instead of `if: github.event_name == 'pull_request'`.
- `SecurityGate` reads each dependency's result via job-scoped runtime expressions (`$[ dependencies.<Job>.result ]`) instead of GitHub's `needs.<job>.result` context — functionally equivalent, different syntax.
- Artifact publishing uses `publish:` (shorthand for `PublishPipelineArtifact@1`) instead of `actions/upload-artifact`.

---

## Step 4.5 — Set up Layer 0 (automated threat modeling)

Two jobs run before every other layer: `ThreatModelBaseline` (Threagile, deterministic, blocking) and `ThreatModelAiAssist` (STRIDE GPT, AI-assisted, advisory).

1. **Threagile** runs via `docker run`. Microsoft-hosted `ubuntu-latest` agents have Docker pre-installed, so no action needed there; self-hosted agents need Docker available.
2. Review `configs/threagile/threagile.yaml` — it ships modeling the *platform's own* reference architecture. **Replace it with your actual system's architecture** (technical assets, data assets, trust boundaries, communication links) before treating its output as a real risk register.
3. The blocking gate is `scripts/check_threagile_risks.py`, run as a plain Python script step (no special ADO task needed) — it fails the job on any critical/high risk without a `risk_tracking:` entry marked `mitigated`, `accepted`, or `false-positive` in the YAML.
4. **STRIDE GPT** reuses the `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` variables from the `ai-security-platform-secrets` group set up in Step 2 — no new secret needed. It runs with `continueOnError: true` and is deliberately excluded from `SecurityGate`'s `dependsOn` list, same reasoning as the PR-fast Garak step: advisory only, a human (or the `threat-modeler` subagent) reviews findings and promotes real ones into a permanent test or rail.
5. Azure Pipelines has no built-in SARIF viewer equivalent to GitHub's code scanning tab. The STRIDE GPT SARIF output is published as a pipeline artifact only; if you want it rendered in the UI, install a marketplace extension like "SARIF SAST Scans Tab" and point it at the `stride-gpt-threat-model` artifact.

## Step 4.6 — Set up Layer 1c/1d (Trivy + OSV-Scanner)

Two more jobs run alongside the rest of Layer 1: `TrivyScan` (filesystem/dependency/IaC CVEs) and `OsvScan` (dependency CVEs via OSV.dev). Both are deterministic, so both are hard-blocking in `SecurityGate` — no new variable group entries needed for either.

1. **Trivy** installs via `curl | sh` from the official install script at the start of the job (Microsoft-hosted agents don't ship it pre-installed, unlike Docker). It scans against `configs/trivy/trivy.yaml` plus the `--severity CRITICAL,HIGH --ignore-unfixed` flags set directly in the pipeline.
2. **OSV-Scanner** runs via `docker run ghcr.io/google/osv-scanner` — same Docker prerequisite as `ThreatModelBaseline` in Step 4.5. Its SARIF output is checked by `scripts/check_osv_results.py`, run as a plain Python step, which fails the job on any SARIF `error`-level (CRITICAL/HIGH) result.
3. Both jobs publish their SARIF as pipeline artifacts (`trivy-report`, `osv-scanner-report`). Same caveat as Step 4.5 note 5 — no native SARIF tab in Azure DevOps without the optional marketplace extension.
4. To accept a specific finding rather than fix it: add a `[[IgnoredVulns]]` block with a reason to `configs/osv-scanner/osv-scanner.toml`, or a `.trivyignore` file at the repo root for Trivy. The point is a version-controlled paper trail, same as Threagile's `risk_tracking:`.

## Step 5 — Authorize the pipeline to use the variable group

Variable groups are not automatically available to every pipeline.

1. Go to **Pipelines → Library**, open `ai-security-platform-secrets`.
2. Click **Pipeline permissions → + → select your pipeline** (or leave it open to "all pipelines" in the project if that fits your security model — scoping to just this pipeline is tighter).
3. Save. If you skip this, the first run will pause waiting for authorization, or fail with a "variable group not found/authorized" error.

---

## Step 6 — Require the Security Gate via branch policy

1. Go to **Repos → Branches**, find `main`, open the **⋮ → Branch policies** menu.
2. Under **Build Validation**, click **+ Add build policy**.
3. Select the pipeline you created in Step 3.
4. Set **Trigger** to **Automatic**, mark it **Required**, and give it a reasonable **Build expiration** (e.g., "Immediately when main is updated" for strict correctness, or a short time window if you want to reduce redundant runs).
5. Save.

Unlike GitHub Actions, Azure Pipelines doesn't let you require an individual *job* as a status check — the build validation policy gates on the whole pipeline run's result. Because `SecurityGate` is the last job and explicitly fails the run (`exit 1`) if any layer failed, this has the same effect: a failing layer fails the pipeline, which blocks the PR.

**If your code is on GitHub but you're running Azure Pipelines as CI against it:** skip this step and instead configure the check in GitHub — **Settings → Branches → branch protection rule → Require status checks** and select the Azure Pipelines check (it will appear once the pipeline has run at least once against a PR). Steps 1–5 and 7–10 are unaffected.

---

## Step 7 — Open a test PR to validate the pipeline end-to-end

1. Create a branch, make a trivial change, and open a PR against `main`.
2. Open the PR's **Checks**/**Build** section and confirm five jobs run (`SupplyChainScan`, `SastScan`, `DataPipelineScan`, `RedTeamScan`, `GuardrailsValidate`), followed by `SecurityGate`.
3. Confirm the PR shows the build validation policy as required and pending/passing appropriately.
4. Deliberately break something to confirm the gate blocks — commit a fake credential (`sk-test1234567890abcdefghij`) to a scratch file and push. `DataPipelineScan` should fail, and the PR should show the branch policy as failed/blocking. Revert afterward.
5. Manually trigger a run with `Build.Reason = Schedule` semantics by using **Run pipeline → Run this pipeline with different variables**, or simply wait for the nightly schedule — confirm the full Garak probe suite runs instead of the fast subset.

---

## Step 8 — Deploy the runtime guardrail proxy (Layer 4)

**Option A — Azure VM (recommended starting point, mirrors the GitHub guide):**

1. Provision a small Linux VM (e.g. `Standard_B2s`) with Docker installed — use the Azure Marketplace "Docker on Ubuntu" image, or install Docker yourself via `az vm run-command`.
2. Copy `docker-compose.guardrails.yml`, a populated `.env` (from `.env.example`), and `configs/nemo-guardrails/` to the VM.
3. Open the needed ports in the VM's Network Security Group: `8001` (guardrails proxy) and `3001` (Langfuse UI), scoped to trusted IP ranges only — do not open these to `0.0.0.0/0` for anything beyond a quick test.
4. Start it:
   ```bash
   docker compose -f docker-compose.guardrails.yml up -d
   ```
5. Point your application at `http://<vm-ip>:8001` instead of calling the model provider directly.
6. Put an Azure Application Gateway or a simple nginx/Caddy reverse proxy with a TLS cert in front before sending real production traffic.

**Option B — Azure Container Instances (lighter-weight, no full VM to patch):**

Deploy just the `guardrails-proxy` service as a single container group. You lose the bundled Langfuse stack (run that separately, or point tracing at Langfuse Cloud instead of self-hosting) but avoid VM patching overhead:
```bash
az container create \
  --resource-group <rg> \
  --name ai-sec-guardrails \
  --image nvcr.io/nvidia/nemo-guardrails:latest \
  --ports 8000 \
  --environment-variables OPENAI_API_KEY=<key> ANTHROPIC_API_KEY=<key> \
  --azure-file-volume-share-name <fileshare-with-configs> \
  --azure-file-volume-mount-path /config \
  --command-line "nemoguardrails server --config=/config --port=8000"
```
(Upload `configs/nemo-guardrails/` to an Azure Files share first and reference it as the volume above.)

---

## Step 9 — Wire up agents and the MCP server (optional but recommended)

Identical to the GitHub setup — this layer is CI/CD-agnostic:

1. Copy `agents/*.md` into `.claude/agents/` in your project.
2. `pip install mcp` and register `mcp/mcp.config.json` with your MCP client (Claude Code, Claude Desktop, or Cowork).
3. Test by asking an agent to run a scan and confirming it invokes the tool rather than shelling out blind.

---

## Step 10 — Confirm the schedule and set retention

1. Check **Pipelines → your pipeline → Runs**, filter for a run with trigger type "Scheduled," and confirm one appears within 24–48 hours after 03:00 UTC.
2. Go to **Project settings → Pipelines → Settings** and review the **Artifacts** retention policy (default is often 30 days) — extend it to match your audit/compliance needs. The `red-team-reports`, `supply-chain-sbom`, `supply-chain-modelscan-report`, and `data-pipeline-report` published artifacts are your evidence trail for Playbook Section 5.2 (Preserve evidence).

---

## Step 11 — Ongoing operation

Hand off to the **AI Security Playbook** (Sections 3, 5, and 6 — runbooks, incident response, maintenance cadence) exactly as in the GitHub setup; nothing in the Playbook is CI/CD-platform-specific.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Run fails immediately with "variable group not authorized" | Complete Step 5 — the pipeline needs explicit permission to use the variable group, separate from the group's own existence. |
| `SecurityGate` shows green even though a layer failed | Check the `continueOnError` note in Step 4 — `SucceededWithIssues` is intentionally treated as passing (it only occurs on the PR-fast, explicitly-non-blocking Garak step). If a job you expect to hard-fail is showing `SucceededWithIssues` instead of `Failed`, check whether `continueOnError: true` was copied onto the wrong step. |
| Pipeline queues but never starts | Parallel jobs exhausted — check **Project settings → Parallel jobs**, or reduce concurrency by adding `dependsOn` between jobs that don't need to run simultaneously. |
| Garak/Promptfoo steps fail with auth errors | Confirm the variable group is linked (Step 5) and the variable names match exactly (`OPENAI_API_KEY`, case-sensitive) — a mismatched name silently resolves to an empty string rather than erroring at parse time. |
| Semgrep step fails immediately with a token error | `SEMGREP_APP_TOKEN` is optional — remove the `env:` line referencing it if you don't have one, rather than leaving the variable group entry blank. |
| SBOM step fails to install Syft | Microsoft-hosted agents occasionally restrict outbound script installers; if `curl \| sh` is blocked in your environment, switch to installing Syft via a pinned release binary download instead of the installer script, or use a self-hosted agent with Syft preinstalled. |
| Nightly run never fires | Scheduled triggers are only evaluated from the YAML file as committed to the branches listed under `schedules: branches: include:` (here, `main`) — confirm the file on `main` actually has the `schedules:` block, not just a feature branch. |
| `ThreatModelBaseline` fails, no `risks.json` produced | Threagile's output layout can shift between versions — run the same `docker run` command locally, inspect what actually lands in `configs/threagile/output/`, and adjust the path passed to `scripts/check_threagile_risks.py` if it differs. |
| `TrivyScan` fails to install via `curl \| sh` | Same class of issue as the Syft installer above — Microsoft-hosted agents occasionally restrict outbound script installers. Download a pinned Trivy release binary directly instead, or use a self-hosted agent with it preinstalled. |
| `OsvScan` job hangs or times out | First-time pull of `ghcr.io/google/osv-scanner` can be slow; re-run once the image is cached on the agent, or use a self-hosted agent pool that persists the Docker image cache between runs. |
| `docker run` fails with permission or "cannot connect to daemon" errors | Confirm the agent pool actually has Docker available — Microsoft-hosted `ubuntu-latest` does; a self-hosted or Windows-based agent pool may not, and would need Docker installed or a Linux pool selected instead. |
