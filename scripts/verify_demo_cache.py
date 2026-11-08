"""Check every demo cache file against the SHA-256 in its manifest.

Usage:
    uv run python scripts/verify_demo_cache.py --help

Writes only gitignored folders (data/demo-cache/, web/public/demo/). See pair.ui.demo_build.
"""

import sys

from pair.ui.demo_build import verify_main

if __name__ == "__main__":
    sys.exit(verify_main())
