.PHONY: install seed api web worker test test-web test-browser check preflight preflight-live stress report
PYTHON := .venv/bin/python

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install uv
	.venv/bin/uv sync --frozen
	npm ci --prefix web

seed:
	$(PYTHON) scripts/seed.py

api:
	.venv/bin/uvicorn pickmate.api.app:app --host 127.0.0.1 --port 8000

web:
	npm run dev --prefix web

worker:
	$(PYTHON) -m pickmate.voice.worker dev

test:
	.venv/bin/pytest -q --junitxml=evidence/pytest.xml

test-web:
	npm test --prefix web
	npm run build --prefix web

test-browser:
	cd web && npm run test:e2e

check:
	.venv/bin/ruff check backend tests scripts
	.venv/bin/ruff format --check backend tests scripts

preflight:
	$(PYTHON) scripts/preflight.py

preflight-live:
	$(PYTHON) scripts/preflight.py --live

stress:
	$(PYTHON) scripts/stress.py --trials 30

report:
	$(PYTHON) scripts/report.py
