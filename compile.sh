#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Pass 1: xelatex ==="
xelatex -interaction=nonstopmode main.tex

echo "=== Biber ==="
biber main

echo "=== Pass 2: xelatex ==="
xelatex -interaction=nonstopmode main.tex

echo "=== Pass 3: xelatex ==="
xelatex -interaction=nonstopmode main.tex

PAGES=$(mdls -name kMDItemNumberOfPages -raw main.pdf 2>/dev/null || echo "?")
echo ""
echo "=== Done: main.pdf ($PAGES pages) ==="
