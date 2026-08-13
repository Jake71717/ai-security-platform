#!/usr/bin/env python3
"""
AI Security Platform - MCP server.

Exposes the platform's open-source security tools as MCP tools, so any
MCP-compatible agent (Claude Code, Claude Desktop, Cowork, etc.) can invoke
scans directly instead of shelling out blind.

Run:
    pip install mcp --break-system-packages
    python mcp/security_tools_server.py

Register (Claude Code / Claude Desktop mcp.json):
    see mcp/mcp.config.json in this folder
"""
import json
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ai-security-platform")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], timeout: int = 900) -> dict:
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout
        )
        return {
            "command": " ".join(cmd),
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-4000:],
        }
    except FileNotFoundError:
        return {"command": " ".join(cmd), "error": f"'{cmd[0]}' not installed. Run scripts/setup.sh first."}
    except subprocess.TimeoutExpired:
        return {"command": " ".join(cmd), "error": f"timed out after {timeout}s"}


@mcp.tool()
def run_threagile_scan(model_path: str = "configs/threagile/threagile.yaml", output_dir: str = "configs/threagile/output") -> str:
    """Run the deterministic Threagile threat model (Layer 0a) against the
    given architecture YAML and return the risk report. Requires Docker."""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}/configs/threagile:/app/work",
        "threagile/threagile",
        "-model", f"/app/work/{Path(model_path).relative_to('configs/threagile')}",
        "-output", f"/app/work/{Path(output_dir).relative_to('configs/threagile')}",
    ]
    result = _run(cmd, timeout=600)
    risks_path = Path(REPO_ROOT) / output_dir / "risks.json"
    try:
        result["risks"] = json.loads(risks_path.read_text())
    except Exception:
        pass
    return json.dumps(result, indent=2)


@mcp.tool()
def run_stride_gpt_analysis(path: str = ".", app_type: str = "genai", max_llm_calls: int = 60) -> str:
    """Run AI-assisted STRIDE GPT threat modeling (Layer 0b, advisory) against
    a codebase path. app_type: 'auto', 'web', 'genai', or 'agentic'.
    Requires OPENAI_API_KEY or ANTHROPIC_API_KEY in the environment."""
    cmd = [
        "stride-gpt", "analyze", path,
        "--app-type", app_type,
        "--max-llm-calls", str(max_llm_calls),
        "-y",
        "-o", "/tmp/stride-gpt-report.json", "-f", "json",
    ]
    result = _run(cmd, timeout=1800)
    try:
        result["parsed_findings"] = json.loads(Path("/tmp/stride-gpt-report.findings.json").read_text())
    except Exception:
        pass
    return json.dumps(result, indent=2)


@mcp.tool()
def scan_model_weights(path: str = ".") -> str:
    """Scan model weight files (pickle/PyTorch/safetensors) at `path` for
    serialization attacks using modelscan and picklescan. Returns JSON."""
    result = {
        "modelscan": _run(["modelscan", "scan", "--path", path, "--report-format", "json"]),
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def run_trivy_scan(path: str = ".", severity: str = "CRITICAL,HIGH") -> str:
    """Run Trivy (Layer 1c) against `path` for filesystem/dependency/IaC
    vulnerabilities and misconfigurations. Returns SARIF as JSON. Requires
    the trivy CLI (scripts/setup.sh installs it)."""
    output_path = REPO_ROOT / "trivy-results.sarif"
    cmd = [
        "trivy", "fs", path,
        "--severity", severity,
        "--ignore-unfixed",
        "--format", "sarif",
        "--output", str(output_path),
    ]
    result = _run(cmd, timeout=900)
    try:
        result["sarif"] = json.loads(output_path.read_text())
    except Exception:
        pass
    return json.dumps(result, indent=2)


@mcp.tool()
def run_osv_scanner(path: str = ".") -> str:
    """Run OSV-Scanner (Layer 1d) against `path` for known-vulnerable
    dependencies via the OSV database. Returns SARIF as JSON. Requires
    Docker (runs ghcr.io/google/osv-scanner)."""
    output_path = REPO_ROOT / "osv-results.sarif"
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{REPO_ROOT}:/src",
        "ghcr.io/google/osv-scanner:latest",
        "scan", "source",
        "--format", "sarif",
        "--output", "/src/osv-results.sarif",
        "--recursive", "/src",
    ]
    result = _run(cmd, timeout=900)
    try:
        result["sarif"] = json.loads(output_path.read_text())
    except Exception:
        pass
    return json.dumps(result, indent=2)


@mcp.tool()
def run_garak_probe(model_type: str, model_name: str, probes: str = "promptinject,leakreplay") -> str:
    """Run NVIDIA Garak adversarial probes against an LLM endpoint.
    model_type: e.g. 'openai', 'huggingface', 'ollama'.
    model_name: e.g. 'gpt-4o-mini'.
    probes: comma-separated probe names, or 'all' for the full suite."""
    cmd = [
        "python", "-m", "garak",
        "--model_type", model_type,
        "--model_name", model_name,
        "--probes", probes,
    ]
    return json.dumps(_run(cmd, timeout=3600), indent=2)


@mcp.tool()
def run_promptfoo_eval(config_path: str = "configs/promptfoo/promptfooconfig.yaml") -> str:
    """Run the Promptfoo eval + red-team suite defined at config_path and
    return the results summary."""
    result = _run(["promptfoo", "eval", "-c", config_path, "--output", "/tmp/promptfoo-eval.json"])
    try:
        result["parsed_results"] = json.loads(Path("/tmp/promptfoo-eval.json").read_text())
    except Exception:
        pass
    return json.dumps(result, indent=2)


@mcp.tool()
def scan_for_secrets(path: str = ".") -> str:
    """Scan the given path for hardcoded API keys / credentials using detect-secrets."""
    return json.dumps(_run(["detect-secrets", "scan", "--all-files", path]), indent=2)


@mcp.tool()
def validate_guardrails_config(config_dir: str = "configs/nemo-guardrails") -> str:
    """Validate that the NeMo Guardrails config at config_dir loads without error."""
    code = (
        "from nemoguardrails import RailsConfig; "
        f"RailsConfig.from_path('{config_dir}'); print('OK')"
    )
    return json.dumps(_run(["python", "-c", code]), indent=2)


if __name__ == "__main__":
    mcp.run()
