#!/usr/bin/env bash
# Build the documentation locally, the same way the documentation workflow
# (.github/workflows/documentation.yml) does. Extra arguments are passed on
# to sphinx-build, e.g. -n to also warn about broken references.
#
# Needs: pip install sphinx sphinx_rtd_theme myst_parser
# Output: docs/build/html/index.html
set -euo pipefail
cd "$(dirname "$0")/.."

# The CLI modules are left out: the CLI is documented by 'ada-cli --help'.
sphinx-apidoc --force --no-toc -o docs/source src/ada src/ada/cli
sphinx-build -M html docs/source docs/build "$@"
