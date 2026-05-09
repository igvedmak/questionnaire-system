# ── Docker (no local tools required) ─────────────────────────────────────────
#
#   make docker-up        — build images + start API (:8000) and UI (:3000)
#   make docker-down      — stop and remove containers
#   make docker-logs      — tail API logs
#   make docker-build     — build images only (no start)
#   make docker-test      — run Python test suite inside Docker (158 tests)
#   make docker-test-ui   — run UI test suite inside Docker (101 tests)
#   make docker-verify    — pytest + qst doctor (all-green gate)
#   make docker-seed      — seed 6 demo templates into the running DB
#
# ── Local dev (requires Python 3.11+ and uv or python3-venv) ─────────────────
#
#   make install          — create .venv and install all extras
#   make verify           — pytest + qst doctor
#   make test             — pytest only
#   make api              — FastAPI on :8000
#   make ui               — Vite dev server on :5173
#   make demo             — seed templates + submit a sample questionnaire
#   make clean            — wipe venv + DB + caches

PY    ?= python3
VENV  ?= .venv
BIN   := $(VENV)/bin
QST   := $(BIN)/qst

UV := $(shell command -v uv 2>/dev/null)

.PHONY: install test verify api ui ui-install ui-build demo clean help \
        docker-build docker-up docker-down docker-logs \
        docker-test docker-test-ui docker-verify docker-seed

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | sed 's/:.*//' | grep -v '^\.' | sort

# ── Docker targets ────────────────────────────────────────────────────────────

docker-up:
	docker compose up -d --build
	@echo "  API → http://localhost:8000/docs"
	@echo "  UI  → http://localhost:3000"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f api

docker-build:
	docker compose build

docker-test:
	docker compose --profile test run --rm api-test

docker-test-ui:
	docker compose --profile test run --rm ui-test

docker-verify: docker-test
	docker compose run --rm api qst doctor

docker-seed:
	docker compose run --rm api qst template seed

# ── Local dev targets ─────────────────────────────────────────────────────────

install:
ifneq ($(UV),)
	$(UV) venv $(VENV)
	$(UV) pip install -e ".[dev,analytics,llm]"
else
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev,analytics,llm]"
endif
	@echo
	@echo "  installed. Try:  make verify"

test:
	$(BIN)/pytest

verify: test
	@echo
	@echo "  pytest green. Now running end-to-end self-test..."
	@echo
	$(QST) doctor

api:
	$(QST) api --host 0.0.0.0 --port 8000

ui-install:
	cd ui && npm install

ui-build:
	cd ui && npm run build

ui: ui-install
	cd ui && npm run dev

demo:
	@rm -f data/db.sqlite data/db.sqlite-*
	$(QST) template seed
	@echo '{"has_allergies":true,"allergy_details":"seeds","contact_method":"Email","date_of_birth":"1991-11-13","age":33,"symptoms":["Fever","Headache"],"fever_duration":"2 days"}' > /tmp/qst_demo_answers.json
	$(QST) answer fill tpl_medical /tmp/qst_demo_answers.json --respondent alice --actor demo
	@echo
	@echo "  demo data ready. Try:"
	@echo "    qst list"
	@echo "    qst list -i contact_method=Email -i symptoms=Fever"
	@echo "    qst audit list"

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__ data/db.sqlite data/db.sqlite-* data/.qst_pii.key ui/dist ui/.node_modules
