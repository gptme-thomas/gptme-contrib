.PHONY: typecheck test format

typecheck:  ## Run mypy type checking on all packages
	@echo "Type checking packages..."
	@for pkg in packages/*/; do \
		if [ -d "$$pkg/src" ]; then \
			echo "Checking $$(basename $$pkg)..."; \
			pipx run mypy "$$pkg/src" --ignore-missing-imports || true; \
		fi \
	done

test:  ## Run all tests
	@echo "Running tests..."
	@for pkg in packages/*/; do \
		if [ -d "$$pkg/tests" ]; then \
			echo "Testing $$(basename $$pkg)..."; \
			pytest "$$pkg/tests" -v; \
		fi \
	done

format:  ## Format code
	ruff format .
	ruff check --fix .

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "%-20s %s\n", $$1, $$2}'
