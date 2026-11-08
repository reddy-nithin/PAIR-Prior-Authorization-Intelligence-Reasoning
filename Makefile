# PAIR task runner. Run `make help` for the list of targets.

.DEFAULT_GOAL := help
.PHONY: help setup test data data-mcd data-imr data-synthea cases eval-core strip-notebooks demo eval demo-cache demo-verify demo-publish demo-fixture api

help: ## List available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-8s %s\n", $$1, $$2}'

setup: ## Install the pinned environment with uv
	uv sync

test: ## Run the test suite with coverage
	uv run pytest --cov=pair --cov-report=term-missing

data: data-mcd data-imr data-synthea ## Download all public datasets into data/raw (gitignored)

data-mcd: ## Download the CMS Medicare Coverage Database CSV exports
	uv run python scripts/download_mcd.py

data-imr: ## Download the California DMHC IMR determinations dataset
	uv run python scripts/download_imr.py

data-synthea: ## Download the pinned Synthea jar (synthetic patients)
	uv run python scripts/download_synthea.py

cases: ## Generate the 30 synthetic eval cases into data/cases (Vertex Gemini)
	uv run python scripts/generate_cases.py

eval-core: ## Score steps 1 to 4 on data/cases and update RESULTS.md (lab E4B by default)
	uv run pair eval-core

strip-notebooks: ## Clear outputs from notebooks/ before committing
	uv run jupyter nbconvert --clear-output --inplace notebooks/*.ipynb

DEMO_INDEX ?= web/public/demo/index.json

demo: ## Build and serve the Next.js demo on http://127.0.0.1:3000 (cached cases; run `make api` too for live runs)
	@test -f $(DEMO_INDEX) || { echo "make demo: no demo cache published at $(DEMO_INDEX). Run 'make demo-cache && make demo-publish' (lab) or 'make demo-fixture' (synthetic, fake models)." >&2; exit 2; }
	npm --prefix web run build
	cd web && npx next start -H 127.0.0.1 -p 3000

demo-cache: ## Build data/demo-cache on the lab pair (needs the tunnel: scripts/lab_ollama.sh start <gpu>)
	uv run python scripts/build_demo_cache.py --require-get-a-human

demo-verify: ## Check the demo cache against its manifest hashes
	uv run python scripts/verify_demo_cache.py

demo-publish: ## Copy the verified demo cache to web/public/demo (gitignored)
	uv run python scripts/publish_demo_cache.py

demo-fixture: ## Publish a one-case demo cache from the synthetic test fixture (fake models; for web dev and Playwright)
	PYTHONPATH=. uv run python scripts/build_fixture_demo.py

api: ## Run the demo API on 127.0.0.1:8000 (PAIR_LIVE=1 for live runs through the lab tunnel)
	uv run uvicorn pair.api.app:app_from_env --factory --host 127.0.0.1 --port 8000 --no-access-log

eval: ## Regenerate RESULTS.md and plots (Phase 5)
	@echo "make eval: not built yet, see Phase 5 (evaluation)" >&2
	@exit 2
