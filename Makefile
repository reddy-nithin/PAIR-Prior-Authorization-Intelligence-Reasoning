# PAIR task runner. Run `make help` for the list of targets.

.DEFAULT_GOAL := help
.PHONY: help setup test data data-mcd data-imr strip-notebooks demo eval

help: ## List available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-8s %s\n", $$1, $$2}'

setup: ## Install the pinned environment with uv
	uv sync

test: ## Run the test suite with coverage
	uv run pytest --cov=pair --cov-report=term-missing

data: data-mcd data-imr ## Download all public datasets into data/raw (gitignored)

data-mcd: ## Download the CMS Medicare Coverage Database CSV exports
	uv run python scripts/download_mcd.py

data-imr: ## Download the California DMHC IMR determinations dataset
	uv run python scripts/download_imr.py

strip-notebooks: ## Clear outputs from notebooks/ before committing
	uv run jupyter nbconvert --clear-output --inplace notebooks/*.ipynb

demo: ## Run the Streamlit demo (Phase 4)
	@echo "make demo: not built yet, see Phase 4 (Streamlit UI)" >&2
	@exit 2

eval: ## Regenerate RESULTS.md and plots (Phase 5)
	@echo "make eval: not built yet, see Phase 5 (evaluation)" >&2
	@exit 2
