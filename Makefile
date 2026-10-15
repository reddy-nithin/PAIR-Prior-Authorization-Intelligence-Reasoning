# PAIR task runner. Run `make help` for the list of targets.

.DEFAULT_GOAL := help
.PHONY: help setup test data demo eval

help: ## List available targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-8s %s\n", $$1, $$2}'

setup: ## Install the pinned environment with uv
	uv sync

test: ## Run the test suite with coverage
	uv run pytest --cov=pair --cov-report=term-missing

data: ## Download policies and IMR data (Phase 1)
	@echo "make data: not built yet, see Phase 1 (scripts/download_imr.py, scripts/download_mcd.py)" >&2
	@exit 2

demo: ## Run the Streamlit demo (Phase 4)
	@echo "make demo: not built yet, see Phase 4 (Streamlit UI)" >&2
	@exit 2

eval: ## Regenerate RESULTS.md and plots (Phase 5)
	@echo "make eval: not built yet, see Phase 5 (evaluation)" >&2
	@exit 2
