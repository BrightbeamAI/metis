# Metis, developer tasks
.PHONY: help install dev demo test lint format regen verify clean

help:
	@echo "Metis make targets:"
	@echo "  install   pip install -e ."
	@echo "  dev       pip install -e '.[dev,api]'"
	@echo "  demo      run the manufacturing pump vibration demo locally"
	@echo "  test      run the pytest suite (no live Ollama required)"
	@echo "  lint      ruff check"
	@echo "  format    ruff format"
	@echo "  regen     rebuild the interactive demo and the example expected outputs"
	@echo "  verify    lint, test, and run the acceptance check"

install:
	pip install -e .

dev:
	pip install -e '.[dev,api]'

demo:
	metis demo manufacturing-pump-vibration

test:
	pytest

lint:
	ruff check metis tests scripts

format:
	ruff format metis tests scripts

regen:
	python scripts/build_demo.py
	python scripts/generate_examples.py

verify:
	ruff check metis tests scripts
	pytest
	python scripts/acceptance_check.py

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache || true
	find . -type d -name __pycache__ -prune -exec rm -rf {} + || true
