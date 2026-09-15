.PHONY: bootstrap validate test check acquire-jitendex census-jitendex ingest-vocabulary ingest-vocabulary-offline match-vocabulary resolve-direct train-fallback infer-fallback adjudicate-residuals finalize package release-candidate

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

resolve-direct:
	$(RUN) -m jlpt_levels resolve-direct

train-fallback:
	$(RUN) -m jlpt_levels train-fallback

infer-fallback:
	$(RUN) -m jlpt_levels infer-fallback

adjudicate-residuals:
	$(RUN) -m jlpt_levels adjudicate-residuals

finalize:
	$(RUN) -m jlpt_levels finalize

package:
	@test -n "$(REVISION)" || (echo "REVISION is required" >&2; exit 2)
	@test -n "$(CREATED_AT)" || (echo "CREATED_AT is required" >&2; exit 2)
	$(RUN) -m jlpt_levels package --revision "$(REVISION)" --created-at "$(CREATED_AT)"

release-candidate:
	@test -n "$(RESOLVED_DATE)" || (echo "RESOLVED_DATE is required" >&2; exit 2)
	$(MAKE) check
	$(MAKE) census-jitendex
	$(MAKE) ingest-vocabulary
	$(MAKE) match-vocabulary
	$(MAKE) resolve-direct
	$(MAKE) train-fallback
	$(MAKE) infer-fallback
	$(MAKE) adjudicate-residuals
	$(MAKE) finalize
	$(MAKE) package REVISION="$(REVISION)" CREATED_AT="$$(printf '%s' '$(RESOLVED_DATE)' | tr . -)T00:00:00Z"
