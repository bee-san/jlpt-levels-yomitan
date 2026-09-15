.PHONY: bootstrap validate test check ingest-vocabulary ingest-vocabulary-offline

PYTHON ?= python
RUN = PYTHONPATH=$(CURDIR)/src $(PYTHON)

bootstrap:
	$(PYTHON) -m pip install -e '.[dev]'

validate:
	$(RUN) -m jlpt_levels validate-contracts

test:
	$(RUN) -m pytest

check: validate test

ingest-vocabulary:
	$(RUN) -m jlpt_levels ingest-vocabulary

ingest-vocabulary-offline:
	$(RUN) -m jlpt_levels ingest-vocabulary --offline
