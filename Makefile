UV ?= uv
PROJECT := pickmate

.PHONY: install api web worker test test-web test-browser check preflight preflight-live

# Some Python installations need an explicit CA bundle for voice providers.
api worker preflight-live: export SSL_CERT_FILE ?= $(shell $(UV) run --frozen --directory $(PROJECT) python -m certifi)

install:
	$(UV) sync --frozen --directory $(PROJECT)
	npm ci --prefix $(PROJECT)/web

api:
	$(UV) run --frozen --directory $(PROJECT) uvicorn counselor.app:app --host 127.0.0.1 --port 8000

worker:
	$(UV) run --frozen --directory $(PROJECT) python -m counselor.worker dev

web:
	npm run dev --prefix $(PROJECT)/web

test:
	$(UV) run --frozen --directory $(PROJECT) python -m pytest -q

test-web:
	npm test --prefix $(PROJECT)/web
	npm run build --prefix $(PROJECT)/web

test-browser:
	npm run test:e2e --prefix $(PROJECT)/web

check:
	$(UV) run --frozen --directory $(PROJECT) ruff check backend tests scripts web/tests
	$(UV) run --frozen --directory $(PROJECT) ruff format --check backend tests scripts web/tests
	npm run typecheck --prefix $(PROJECT)/web

preflight:
	$(UV) run --frozen --directory $(PROJECT) python scripts/preflight.py --offline

preflight-live:
	$(UV) run --frozen --directory $(PROJECT) python scripts/preflight.py --live
