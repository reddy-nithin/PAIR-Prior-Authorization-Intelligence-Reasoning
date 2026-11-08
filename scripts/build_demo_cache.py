"""Build the demo cache: steps 1 to 7 on a few synthetic cases (lab E4B + MiniCheck through the tunnel).

Usage:
    uv run python scripts/build_demo_cache.py --help

Writes only gitignored folders (data/demo-cache/, web/public/demo/). See pair.ui.demo_build.
"""

import sys

from pair.ui.demo_build import build_main

if __name__ == "__main__":
    sys.exit(build_main())
