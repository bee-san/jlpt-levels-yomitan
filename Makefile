.PHONY: bootstrap validate test check acquire-jitendex census-jitendex ingest-vocabulary ingest-vocabulary-offline match-vocabulary train-fallback infer-fallback

PYTHON ?= python
RUN = PYTHONPATH=$(CURDIR)/src $(PYTHON)

bootstrap:
	$(PYTHON) -m pip install -e '.[dev]'

validate:
	$(RUN) -m jlpt_levels validate-contracts

test:
	$(RUN) -m pytest

check: validate test

acquire-jitendex:
	$(RUN) -m jlpt_levels acquire-jitendex

census-jitendex: acquire-jitendex
	$(RUN) -m jlpt_levels census-jitendex data/cache/jitendex/8364e69e7bd0881c42011e96af921a7399d7fe06e2bf4fff4da6d18affff74fc.zip

ingest-vocabulary:
	$(RUN) -m jlpt_levels ingest-vocabulary

ingest-vocabulary-offline:
	$(RUN) -m jlpt_levels ingest-vocabulary --offline

match-vocabulary:
	$(RUN) -m jlpt_levels match-vocabulary

train-fallback:
	$(RUN) -m jlpt_levels train-fallback

infer-fallback:
	$(RUN) -m jlpt_levels infer-fallback
