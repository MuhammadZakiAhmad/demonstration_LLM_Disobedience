#!/usr/bin/env bash
# Install pinned inference/test dependencies in the current Colab Python runtime.
# Run from anywhere: it changes into the repository root itself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Repository: $ROOT"
python - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit(
        f"Python 3.9+ is required; this runtime has {sys.version.split()[0]}"
    )
print(f"Python: {sys.version.split()[0]}")
PY

echo
echo "Installing pinned dependencies from requirements.txt ..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p logs results

python - <<'PY'
import torch
import transformers

print()
print(f"torch: {torch.__version__}")
print(f"transformers: {transformers.__version__}")
if not torch.cuda.is_available():
    raise SystemExit(
        "\nNo CUDA GPU is visible. In Colab choose Runtime > Change runtime type > "
        "T4 GPU, then rerun this setup script. The model server does not fall back "
        "to CPU automatically."
    )
print(f"CUDA device: {torch.cuda.get_device_name(0)}")
free, total = torch.cuda.mem_get_info(0)
print(f"GPU memory: {free / 1024**3:.2f} GiB free of {total / 1024**3:.2f} GiB")
PY

python environment_report.py --output logs/environment_setup.txt

cat <<'EOF'

Setup complete.
Next steps:
  1. bash scripts/start_model.sh
  2. bash scripts/check_model.sh
  3. bash scripts/run_experiment.sh

The first model start downloads roughly 3.5 GB and can take several minutes.
EOF
