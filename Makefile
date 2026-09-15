.PHONY: bootstrap validate test check

bootstrap:
	python -m pip install -e '.[dev]'

validate:
	python -m jlpt_levels validate-contracts

test:
	python -m pytest

check: validate test
