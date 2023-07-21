.PHONY: flake8 isort isort-fix black black-fix lint-all

# Directory to run the linters on
DIR = .

flake8:
	@echo "Running Flake8"
	@poetry run flake8 $(DIR)

isort:
	@echo "Running isort"
	@poetry run isort --check --diff $(DIR)

isort-fix:
	@echo "Running isort (fix)"
	@poetry run isort $(DIR)

black:
	@echo "Running Black"
	@poetry run black --check $(DIR)

black-fix:
	@echo "Running Black (fix)"
	@poetry run black $(DIR)

lint-all: flake8 isort black
	@echo "Linting complete"
