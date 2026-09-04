# AI Security Platform

A turnkey, open-source MLSecOps platform: architecture, CI/CD pipeline,
runtime guardrails, red-teaming, subagents, and an MCP server that wires it
all together for agent-driven operation.

Companion documents (in `docs/`): **AI Security Architecture Document** and
**AI Security Playbook** - read those first for the why; this repo is the how.

## What's here

```
.github/workflows/ai-security-scan.yml   GitHub Actions CI/CD pipeline - all 4 layers, PR + nightly
azure-pipelines.yml                      Azure DevOps equivalent of the same pipeline
docs/
  IMPLEMENTATION-GITHUB.md   Step-by-step setup guide for GitHub
  IMPLEMENTATION-ADO.md       Step-by-step setup guide for Azure DevOps
configs/
  threagile/         Deterministic architecture threat model + vendored schema.json (Layer 0a)
  garak/            Adversarial LLM probe notes (Layer 3)
  promptfoo/         Eval + red-team suite config (Layer 3)
  semgrep/           AI/ML-specific SAST rules (Layer 1)
  trivy/             Filesystem/IaC vulnerability scan config (Layer 1c)
  osv-scanner/        Dependency CVE scan + ignore list (Layer 1d)
  nemo-guardrails/    Runtime input/output rails (Layer 4)
docker-compose.guardrails.yml   Runtime guardrail proxy + Langfuse tracing, deployable as-is
scripts/
  setup.sh            One-shot local tool install
  run_local_scan.sh    Run all layers locally
  check-eval-threshold.js       CI pass-rate gate (Layer 3)
  check_threagile_model.py      Structural validation of the Threagile model (pre-commit + CI fail-fast, Layer 0a)
  check_threagile_risks.py       CI blocking gate for untriaged Threagile risks (Layer 0a)
  check_osv_results.py       CI blocking gate for CRITICAL/HIGH OSV-Scanner findings (Layer 1d)
agents/               Claude Code-style subagent definitions (threat modeler,
                       supply chain, red team, guardrails, incident response)
mcp/                  MCP server exposing the scanners as agent-callable tools
policies/security-gate-policy.md   Human-readable version of the CI gate rules
```

## Quick start

For a full guided setup, use `docs/IMPLEMENTATION-GITHUB.md` or `docs/IMPLEMENTATION-ADO.md` depending on your CI/CD platform. Short version:

```bash
git clone <this-repo> && cd ai-security-platform
cp .env.example .env   # fill in API keys
./scripts/setup.sh
./scripts/run_local_scan.sh
```

Optional but recommended - install the pre-commit hooks so the Threagile
model is structurally validated (schema + cross-references) on every commit:

```bash
pip install pre-commit && pre-commit install
```

To run the runtime guardrail proxy + observability stack:
```bash
docker compose -f docker-compose.guardrails.yml up -d
```

To give an agent (Claude Code, Claude Desktop, Cowork) direct access to the
scanners, register `mcp/mcp.config.json` as an MCP server, or drop
`agents/*.md` into your project's `.claude/agents/` directory to get
purpose-built subagents for each layer.

## Tool inventory (all free / open source)

| Layer | Tools |
|---|---|
| 0. Automated threat modeling | Threagile (deterministic, blocking), STRIDE GPT (AI-assisted, advisory) |
| 1. Supply chain & model integrity | ModelScan, Picklescan, Syft (SBOM), Semgrep, Trivy (filesystem/IaC CVEs), OSV-Scanner (dependency CVEs) |
| 2. Data & pipeline integrity | detect-secrets |
| 3. Model robustness & red teaming | NVIDIA Garak, Promptfoo, Microsoft PyRIT (optional, see docs) |
| 4. Runtime guardrails | NVIDIA NeMo Guardrails, Meta Purple Llama (Llama Guard / Prompt Guard) |
| Observability | Langfuse |

## Status notes (as of Aug 2026)

- **Promptfoo** was acquired by OpenAI (announced Mar 2026) and remains open
  source under its existing license - no action needed.
- **ModelScan** is now community-maintained after Protect AI's acquisition
  by Palo Alto Networks (2025); still usable, but track the fork/community
  repo for security patches.
- **Garak** is actively maintained by NVIDIA (v0.14.0, Feb 2026).
- **Threagile** is community-driven (MIT license), actively maintained.
- **STRIDE GPT** is actively maintained; the CLI (`pip install stride-gpt`)
  now ships separately from the legacy Streamlit web UI and tags findings
  with MITRE ATT&CK/ATLAS technique IDs.
- **Trivy** (Aqua Security, Apache-2.0) is one of the most widely adopted OSS
  vulnerability scanners (30k+ GitHub stars) and is actively maintained.
- **OSV-Scanner** (Google, Apache-2.0) queries the community-run OSV.dev
  database; actively maintained, runs here via the official Docker image so
  no local Go toolchain is required.
