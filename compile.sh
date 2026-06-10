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

## =============================================================================
## PRESENTATION BUILD  (opt-in — NEVER breaks the thesis build above)
##
## To build the Beamer deck:
##   BUILD_PRES=1 ./compile.sh
## or independently:
##   cd presentation && xelatex slides.tex && xelatex slides.tex
##
## Engine: XeLaTeX, 2 passes.  Output: presentation/slides.pdf
## SAFETY: the subshell failure is caught by '||' — a broken slides.tex
## will never cause this script to exit non-zero for the thesis consumer.
## =============================================================================
if [ "${BUILD_PRES:-0}" = "1" ]; then
  echo ""
  echo "=== Building presentation (slides.tex) ==="
  (
    cd "$(dirname "$0")/presentation"
    echo "=== Presentation Pass 1: xelatex ==="
    xelatex -interaction=nonstopmode slides.tex
    echo "=== Presentation Pass 2: xelatex (cross-refs) ==="
    xelatex -interaction=nonstopmode slides.tex
    SPAGES=$(mdls -name kMDItemNumberOfPages -raw slides.pdf 2>/dev/null || echo "?")
    echo ""
    echo "=== Done: presentation/slides.pdf ($SPAGES slides total) ==="
  ) || {
    echo ""
    echo "=== WARNING: Presentation build FAILED (non-fatal — thesis build is OK) ==="
  }
fi
