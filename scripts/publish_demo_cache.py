"""Copy a verified demo cache to web/public/demo/ for the web app's cached mode.

Usage:
    uv run python scripts/publish_demo_cache.py --help

Writes only gitignored folders (data/demo-cache/, web/public/demo/). See pair.ui.demo_build.
"""

import sys

from pair.ui.demo_build import publish_main

if __name__ == "__main__":
    sys.exit(publish_main())
