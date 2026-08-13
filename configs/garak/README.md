# Garak configuration

Garak (https://github.com/NVIDIA/garak) is invoked directly from the CLI in
`.github/workflows/ai-security-scan.yml` rather than a single static config
file, because probe selection differs between the fast PR run and the nightly
full run. Use this file to keep the canonical probe lists in sync.

## PR-fast probe set (~3-5 min)
promptinject, leakreplay, malwaregen

## Nightly full probe set (~30-90 min depending on model)
all probes, i.e. `--probes all` - covers dan, encoding, glitch, hallucination,
knownbadsignatures, leakreplay, malwaregen, promptinject, realtoxicityprompts,
xss, and more. See `python -m garak --list_probes` for the current catalog.

## Local run
```bash
pip install garak
export OPENAI_API_KEY=...
python -m garak --model_type openai --model_name gpt-4o-mini --probes promptinject
```

## Targeting a self-hosted model
```bash
python -m garak --model_type huggingface --model_name your-org/your-model --probes all
```
