# Metis, developer tasks
PYTHON ?= python3

.PHONY: help install dev demo test lint format regen verify build publish clean

help:
	@echo "Metis make targets:"
	@echo "  install   pip install -e ."
	@echo "  dev       pip install -e '.[dev,api]' (includes build and twine)"
	@echo "  demo      run the manufacturing pump vibration demo locally"
	@echo "  test      run the pytest suite (no live Ollama required)"
	@echo "  lint      ruff check"
	@echo "  format    ruff format"
	@echo "  regen     rebuild the interactive demo and the example expected outputs"
	@echo "  verify    lint, test, and run the acceptance check"
	@echo "  build     build sdist and wheel into dist/"
	@echo "  publish   upload dist/* to PyPI with twine (needs PyPI token)"

install:
	$(PYTHON) -m pip install -e .

dev:
	$(PYTHON) -m pip install -e '.[dev,api]'

demo:
	metis demo manufacturing-pump-vibration

test:
	$(PYTHON) -m pytest

lint:
	ruff check metis tests scripts

format:
	ruff format metis tests scripts

regen:
	$(PYTHON) scripts/build_demo.py
	$(PYTHON) scripts/generate_examples.py

verify:
	ruff check metis tests scripts
	$(PYTHON) -m pytest
	$(PYTHON) scripts/acceptance_check.py

build: clean
	$(PYTHON) scripts/build_pypi_readme.py
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*

publish: build
	$(PYTHON) -m twine upload dist/*

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache || true
	find . -type d -name __pycache__ -prune -exec rm -rf {} + || true
