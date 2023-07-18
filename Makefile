.PHONY: flake8 isort isort-fix black black-fix lint-all

# Directory to run the linters on
DIR = .

flake8:
	@echo "Running Flake8"
	@flake8 $(DIR)

isort:
	@echo "Running isort"
	@isort --check --diff $(DIR)

isort-fix:
	@echo "Running isort (fix)"
	@isort $(DIR)

black:
	@echo "Running Black"
	@black --check $(DIR)

black-fix:
	@echo "Running Black (fix)"
	@black $(DIR)

lint-all: flake8 isort black
	@echo "Linting complete"
