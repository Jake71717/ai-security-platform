#!/usr/bin/env bash
# Runs all layers locally, mirroring the CI pipeline, for fast iteration.
set -euo pipefail

echo "[1/6] Supply chain: modelscan + picklescan"
find . -type f \( -name "*.pkl" -o -name "*.pt" -o -name "*.pth" -o -name "*.safetensors" \) \
  -exec modelscan scan --path {} \; || true

echo "[2/6] Vulnerability scan: trivy (Layer 1c)"
trivy fs . --severity CRITICAL,HIGH --ignore-unfixed --config configs/trivy/trivy.yaml || true

echo "[3/6] Dependency vulnerability scan: osv-scanner (Layer 1d)"
docker run --rm -v "$(pwd):/src" ghcr.io/google/osv-scanner:latest \
  scan source --recursive /src || true

echo "[4/6] Data pipeline: detect-secrets"
detect-secrets scan --all-files || true

echo "[5/6] Red team: garak + promptfoo"
python -m garak --model_type openai --model_name gpt-4o-mini --probes promptinject,leakreplay || true
promptfoo eval -c configs/promptfoo/promptfooconfig.yaml || true

echo "[6/6] Guardrails config validation"
python -c "from nemoguardrails import RailsConfig; RailsConfig.from_path('configs/nemo-guardrails'); print('OK')"

echo "Local scan complete."
