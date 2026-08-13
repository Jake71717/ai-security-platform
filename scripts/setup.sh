#!/usr/bin/env bash
# One-shot local bootstrap for the AI Security Platform.
set -euo pipefail

echo "== Installing Python security tooling =="
pip install --break-system-packages \
  garak \
  modelscan \
  picklescan \
  nemoguardrails \
  detect-secrets

echo "== Installing Node tooling =="
npm install -g promptfoo

echo "== Installing Trivy (Layer 1c) =="
curl -sSfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

echo "== OSV-Scanner (Layer 1d) runs via Docker - no local install needed =="
echo "   docker pull ghcr.io/google/osv-scanner:latest"

echo "== Verifying installs =="
python -m garak --version || true
modelscan --version || true
promptfoo --version || true
trivy --version || true

cat <<MSG

Setup complete. Next steps:
  1. Copy .env.example to .env and fill in API keys.
  2. Run './scripts/run_local_scan.sh' for a full local pass.
  3. Start the runtime guardrail proxy: docker compose -f docker-compose.guardrails.yml up -d
  4. Push to a branch - the GitHub Actions pipeline in .github/workflows/ai-security-scan.yml
     will run automatically.
MSG
