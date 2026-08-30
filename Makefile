.PHONY: setup baseline baseline-live audit evaluate evaluate-live ablations demo api test quality-gate official-quality-gate prepare-submission package verify-package

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
FIXTURE_ENV := RG_OFFLINE_MODE=1
LIVE_PROVIDER ?= xai
LIVE_MODEL ?= grok-4.6
LIVE_PROMPT_VERSION ?= final-v2
LIVE_BASE_ENV := RG_OFFLINE_MODE=0 RG_LLM_PROVIDER=$(LIVE_PROVIDER) RG_MODEL_ID=$(LIVE_MODEL) RG_PROMPT_VERSION=b1-v1
LIVE_FINAL_ENV := RG_OFFLINE_MODE=0 RG_LLM_PROVIDER=$(LIVE_PROVIDER) RG_MODEL_ID=$(LIVE_MODEL) RG_PROMPT_VERSION=$(LIVE_PROMPT_VERSION)

# The system interpreter is used only for the one-time bootstrap that creates
# the virtualenv. Every project command below runs through $(PYTHON).

setup:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtualenv at $(VENV)..."; \
		python3 -m venv $(VENV); \
	fi
	$(PIP) install --disable-pip-version-check --requirement requirements.lock
	$(PIP) install --disable-pip-version-check --no-build-isolation --no-deps --editable ".[dev]"
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
	else \
		echo ".env already exists, leaving it untouched"; \
	fi

baseline:
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode baseline --label baseline_$(shell date +%Y%m%d_%H%M%S)

baseline-live:
	$(LIVE_BASE_ENV) $(PYTHON) -m eval.run --mode baseline --label baseline_$(LIVE_PROVIDER)_$(shell date +%Y%m%d_%H%M%S)

audit:
	$(PYTHON) -m app.cli audit --case eval/cases/$(CASE) --mode $(or $(MODE),final)

evaluate:
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode final --label final_$(shell date +%Y%m%d_%H%M%S)

evaluate-live:
	$(LIVE_FINAL_ENV) $(PYTHON) -m eval.run --mode final --label final_$(LIVE_PROVIDER)_$(shell date +%Y%m%d_%H%M%S)

ablations:
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode final --ablation no_verifier --label ablation_no_verifier_$(shell date +%Y%m%d_%H%M%S)
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode final --ablation no_evidence_enforcement --label ablation_no_evidence_enforcement_$(shell date +%Y%m%d_%H%M%S)
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode final --ablation no_deterministic_checks --label ablation_no_deterministic_checks_$(shell date +%Y%m%d_%H%M%S)
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode final --ablation no_tool_output_normalization --label ablation_no_tool_output_normalization_$(shell date +%Y%m%d_%H%M%S)
	$(FIXTURE_ENV) $(PYTHON) -m eval.run --mode final --ablation it5_subagents --label ablation_it5_subagents_$(shell date +%Y%m%d_%H%M%S)

demo:
	$(FIXTURE_ENV) $(MAKE) audit CASE=$(or $(CASE),case_12) MODE=final

api:
	$(PYTHON) -m uvicorn app.api.main:app --reload --port 8000

test:
	$(PYTHON) -m pytest -q

quality-gate:
	$(PYTHON) scripts/check_quality_gates.py --baseline submission/results/baseline/results.json --final submission/results/final/results.json

official-quality-gate:
	$(PYTHON) scripts/check_quality_gates.py --baseline submission/results/live_provider/baseline/results.json --final submission/results/live_provider/final/results.json --out submission/results/official_live_quality_gates.json --require-live

prepare-submission:
	$(PYTHON) scripts/prepare_submission.py

package: prepare-submission quality-gate
	$(PYTHON) scripts/package_submission.py

verify-package: package
	$(PYTHON) scripts/verify_submission_zip.py dist/releaseguard_submission.zip
