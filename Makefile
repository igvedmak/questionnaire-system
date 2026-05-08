# Zero-touch dev workflow.
#
# Local dev:
# `make install`       — create venv and install everything (analytics extra included).
# `make verify`        — pytest (158 tests) + qst doctor (124 checks).
# `make test`          — pytest only.
# `make api`           — start the FastAPI server on :8000.
# `make demo`          — seed templates + submit a sample questionnaire.
# `make clean`         — wipe venv + DB + caches.
#
# Docker:
# `make docker-up`     — build image + start API at http://localhost:8000.
# `make docker-down`   — stop containers.
# `make docker-logs`   — tail API logs.
# `make docker-build`  — build image only.

PY    ?= python3
VENV  ?= .venv
BIN   := $(VENV)/bin
QST   := $(BIN)/qst

# Prefer uv if available (fast); fall back to stdlib venv + pip.
UV := $(shell command -v uv 2>/dev/null)

.PHONY: install test verify api demo clean help docker-build docker-up docker-down docker-logs

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | sed 's/:.*//' | grep -v '^\.' | sort

install:
ifneq ($(UV),)
	$(UV) venv $(VENV)
	$(UV) pip install -e ".[dev,analytics]"
else
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev,analytics]"
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

docker-build:
	docker build -t questionnaire-engine .

docker-up:
	docker compose up -d
	@echo "  API running at http://localhost:8000/docs"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f api

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__ data/db.sqlite data/db.sqlite-* data/.qst_pii.key
