.PHONY: ruff ruff-fix

# Directory to run the linters on
DIR = .

ruff:
	@echo "Running Flake8"
	@poetry run ruff check $(DIR)
	@poetry run ruff format --check $(DIR)

ruff-fix:
	@echo "Running Black (fix)"
	@poetry run ruff check --fix $(DIR)
	@poetry run ruff format $(DIR)
