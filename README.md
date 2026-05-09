# Questionnaire Engine

A programmable questionnaire engine — templates with expression-based
follow-ups, instances answered through a CLI or HTTP API, indexed
filtering, tamper-evident audit log, encrypted PII fields, GDPR
export/delete, semantic clustering of free-text answers, and
**AI-powered template generation and response analysis**.

Implements the original home-assignment spec in full and extends it
toward a credible product foundation.

---

## Highlights

| Feature | Where |
|---|---|
| **8 question types**: boolean, single-select, multi-select, date, free-text, number, **rating**, **email** | `domain/types.py` |
| **Recursive follow-ups** with two trigger shapes (legacy equality + arbitrary expression AST) | `domain/expression.py`, `domain/flow.py` |
| Single tree-walker (`resolve_active_questions`) drives CLI, validation, rendering, and the API | `domain/flow.py` |
| Two-tier validation: structural template rules, per-type answer rules via **Validator strategy** registry | `domain/validation.py` |
| **SQLite store** with indexed answer rows; AND/OR/NOT filters push down to SQL | `persistence/sql_store.py` |
| **Template versioning**: edits append a new version; questionnaires snapshot the version they were created against | `persistence/sql_store.py` |
| **Submission immutability**: once submitted, answers are frozen at the SQL layer | `persistence/sql_store.py` |
| **Audit log** with SHA-256 hash chain (tamper-evident) | `domain/audit.py`, audit table |
| **PII encryption at rest** (Fernet) for fields flagged `pii: true` | `domain/encryption.py` |
| **GDPR export & delete** by respondent id | `persistence/sql_store.py`, `/respondents/{id}` endpoints |
| **HTTP API** (FastAPI) mirroring the CLI 1:1, OpenAPI auto-generated | `api/app.py` |
| **API key auth** — set `QST_API_KEYS` to enable; `X-API-Key` header required for writes | `api/app.py` |
| **CSV export** of filtered queries, streamed | `cli/query_cmd.py`, `/questionnaires.csv` |
| **Semantic free-text clustering** (HDBSCAN over sentence-transformer embeddings) — optional `analytics` extra | `analytics/clustering.py` |
| **AI template generation** — natural-language description → validated Template via configurable LLM (litellm, 100+ providers) | `llm/generate.py` |
| **AI response analysis** — streaming narrative report over submitted responses via configurable LLM | `llm/analyze.py` |
| **Webhooks** — HMAC-signed HTTP callbacks for `questionnaire.submit` and `gdpr.delete` events | `persistence/sql_store.py`, `/webhooks` endpoints |
| **Template duplication** — clone any template to a new id | `persistence/sql_store.py`, `/templates/{id}/duplicate` |
| **Template stats** — submission counts and completion rate per template | `/templates/{id}/stats` |
| **Migration** from the legacy JSON store via `qst migrate` | `persistence/migrate.py` |
| **OR / NOT filter combinators**: `OrFilter(filters=[...])` and `NotFilter(inner=...)` nest inside the flat AND list | `domain/filtering.py` |
| **158 tests** covering domain, store, audit, encryption, expression engine, migration, API, and one end-to-end `qst doctor` wrapper | `tests/` |
| **`qst doctor`** — 124 checks across 11 sections (types, expressions, filters, lifecycle, audit, GDPR, versioning, validation, migration, HTTP API, analytics); exits 0/1 | `cli/doctor_cmd.py` |
| **`check_cli.sh`** — 53 bash end-to-end checks with full log output per command; `bash check_cli.sh` | `check_cli.sh` |
| **`qst answer fill`** — non-interactive submission from a JSON file (CI / agents) | `cli/answer_cmd.py` |
| **`Makefile`** — one-shot `make install` / `make verify` / `make demo` | top-level |

---

## Run

**Only prerequisite: [Docker](https://docs.docker.com/get-docker/) (Desktop or Engine).**
No Python, Node, pip, or npm required on your machine.

### Quickstart

```bash
cp .env.example .env    # edit if you want AI features (set QST_LLM_API_KEY)
docker compose up -d    # builds images, starts API :8000 + UI :3000
```

Open **http://localhost:3000** for the UI, or **http://localhost:8000/docs** for the API.

Data (SQLite DB, PII key) is persisted in `./data/` on the host.
HuggingFace model files are cached in a named Docker volume (`hf_cache`)
so they aren't re-downloaded on restart.

### All Docker commands

| Command | What it does |
|---|---|
| `docker compose up -d` | Start API + UI in the background |
| `docker compose down` | Stop and remove containers |
| `docker compose logs -f api` | Tail API logs |
| `docker compose run --rm api qst doctor` | 124-check self-test |
| `docker compose run --rm api qst template seed` | Seed 6 demo templates |
| `docker compose run --rm api qst audit verify` | Verify hash chain |
| `make docker-test` | Run Python test suite (158 tests) inside Docker |
| `make docker-test-ui` | Run UI test suite (101 tests) inside Docker |
| `make docker-verify` | pytest + qst doctor — all-green gate |
| `make docker-seed` | Seed demo templates into running DB |

Or directly without `make`:

```bash
docker compose --profile test run --rm api-test    # Python tests
docker compose --profile test run --rm ui-test     # UI tests
```

### AI features

Set these in `.env` before `docker compose up`:

```bash
# Anthropic Claude (default):
QST_LLM_API_KEY=sk-ant-...
QST_LLM_MODEL=anthropic/claude-opus-4-7

# OpenAI:
QST_LLM_API_KEY=sk-...
QST_LLM_MODEL=gpt-4o

# Google Gemini:
QST_LLM_API_KEY=AIza...
QST_LLM_MODEL=gemini/gemini-1.5-pro

# Local Ollama (no key needed — Ollama must be running on the host):
QST_LLM_MODEL=ollama/llama3
QST_LLM_BASE_URL=http://host.docker.internal:11434
```

Without `QST_LLM_API_KEY`, the engine runs fully; AI endpoints return 503.

### PII encryption key

Zero setup needed — the engine auto-generates a Fernet key on first boot
and persists it to `data/.qst_pii.key` (gitignored, `chmod 0600`).
In production, set `QST_PII_KEY` from your secret manager instead.
Generate a key with:

```bash
docker compose run --rm api python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Local dev (optional — only needed if you are editing the source code)

> If you just want to run the app, `docker compose up -d` is all you need.
> This section is for contributors who want hot-reload, a debugger, or to run tests without Docker.

Requires Python 3.11+ and Node 20+.

```bash
make install               # creates .venv, installs all extras (uv preferred, falls back to venv)
source .venv/bin/activate
make verify                # pytest (158 tests) + qst doctor (124 checks)
make api                   # FastAPI on :8000
make ui                    # Vite dev server on :5173 (separate terminal)
```

> Ubuntu/Debian: run `sudo apt install python3.12-venv` before `make install` if you don't have `uv`.

### A 60-second tour

Run these with `docker compose run --rm api` (or locally after `source .venv/bin/activate`):

```bash
qst doctor                           # 124-check self-test — exits 0 on green

qst template seed                    # seed 6 demo templates
qst template list                    # list current versions
qst template show tpl_medical        # show questions + follow-up tree
qst template show tpl_medical -v 1   # show a specific version

qst answer start tpl_medical \
    --respondent alice               # interactive; follow-ups appear as triggers fire
qst answer resume <questionnaire_id> # resume a draft

# Non-interactive fill from a JSON file (CI / scripts / agents):
cat > /tmp/answers.json <<'EOF'
{"has_allergies":true,"allergy_details":"seeds","contact_method":"Email","date_of_birth":"1991-11-13","age":33,"symptoms":["Fever","Headache"],"fever_duration":"2 days"}
EOF
qst answer fill tpl_medical /tmp/answers.json --respondent alice
# Note: when the analytics extra is installed, the first fill per session
# prints HuggingFace model loading progress — this is normal.

qst list                             # all submitted questionnaires
qst list -t tpl_medical \
    -i contact_method=Email \
    -i symptoms=Fever                # AND of three filters

qst export submissions.csv -t tpl_medical   # CSV export

qst audit list                       # every state-change event
qst audit verify                     # verify SHA-256 hash chain

qst gdpr export alice alice.zip      # GDPR export zip for respondent alice
qst gdpr delete alice --yes          # permanent hard-delete, audit-logged

qst api --port 8000                  # start HTTP API
# then open: http://localhost:8000   (redirects to /docs automatically)
```

```bash
# Migrate from a legacy JSON store (data/db.json → data/db.sqlite):
qst migrate
```

#### AI-powered features (set `QST_LLM_API_KEY` in `.env` — see [AI features](#ai-features) above)

```bash
# Generate a template from a plain-English description:
qst template ai-generate "Employee satisfaction survey covering workload, culture, and career growth"

# Dry-run (preview without saving):
qst template ai-generate "Event feedback form" --dry-run

# Stream an AI analysis report of all submitted responses:
qst analytics ai-analyze tpl_medical
```

---

## Web UI

A React + Vite + TypeScript + Tailwind CSS frontend lives in [`ui/`](ui/).

### Start in development

```bash
# Terminal 1 — API
make api        # FastAPI at http://localhost:8000

# Terminal 2 — UI
make ui         # Vite dev server at http://localhost:5173
```

The UI reads `VITE_API_URL` from `ui/.env` (defaults to `http://localhost:8000`).
CORS is open by default so cross-origin requests work out of the box.

### Production build

```bash
make ui-build   # outputs to ui/dist/ — serve with any static host
```

### Features

| Page | What it does |
|---|---|
| **Templates** (`/`) | Template library with stats; one-click start; **AI Generate modal** |
| **Fill** (`/fill/:id`) | Dynamic questionnaire form — all 8 question types, live follow-up reveal, auto-save per answer, progress bar, submit |
| **Responses** (`/responses`) | Paginated response table; filter by template or draft status; slide-over detail panel; per-row actions (view, archive, delete); CSV export |

All 8 question types have purpose-built inputs:
- Boolean → Yes / No toggle buttons
- Single-select → Radio-style option cards
- Multi-select → Checkbox option cards
- Date → Native date picker
- Free text → Auto-resizable textarea (PII badge when encrypted)
- Number → Validated numeric input with min/max hint
- Rating → Clickable number scale with labels
- Email → Email input with validation

Follow-up questions animate in below their parent as soon as the trigger fires — no page reload, no manual save.

---

## HTTP API

Boot:

```bash
qst api --host 0.0.0.0 --port 8000
# or: make api
# or: docker compose up -d
# then open: http://localhost:8000   (redirects to /docs automatically)
```

Auth: set `QST_API_KEYS=key1,key2` to require `X-API-Key: <key>` on write endpoints.
Read endpoints are always public. The `X-Actor` header (optional) is recorded in the audit log.

Endpoints:

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | DB connectivity check |
| POST | `/templates` | New template (auto v1) or new version (if id is reused) |
| GET | `/templates` | List current versions |
| GET | `/templates/{id}` | `?version=` for a specific version |
| GET | `/templates/{id}/versions` | All versions |
| GET | `/templates/{id}/stats` | Submission count and completion rate |
| POST | `/templates/{id}/duplicate` | Clone to a new id (`?new_id=`) |
| POST | `/templates/ai-generate` | Generate from plain-English description (`?save=false` to preview) |
| POST | `/questionnaires` | Start an instance |
| GET | `/questionnaires/{id}` | Get with answers |
| GET | `/questionnaires` | Filter via `?template=`, `?includes=qid=val`, `?excludes=qid=val`, `?include_drafts=`, `?page=`, `?page_size=` |
| PUT | `/questionnaires/{id}/answers/{qid}` | Upsert one answer (rejected with 409 after submit) |
| PUT | `/questionnaires/{id}/answers` | Bulk upsert answers |
| DELETE | `/questionnaires/{id}/answers/{qid}` | Remove one answer (rejected with 409 after submit) |
| POST | `/questionnaires/{id}/submit` | Lock the questionnaire |
| POST | `/questionnaires/{id}/archive` | Soft-archive (sets `archived_at`) |
| DELETE | `/questionnaires/{id}` | Hard-delete (audit-logged) |
| POST | `/questionnaires/{id}/validate` | Validate without submitting |
| GET | `/questionnaires.csv` | Streaming CSV of the filtered set |
| GET | `/llm/config` | Active LLM provider name, model, and whether a key is configured |
| GET | `/audit?since=<seq>` | Audit log entries |
| POST | `/audit/verify` | Recompute the chain, 200 OK or 409 |
| GET | `/respondents/{id}/export` | GDPR zip |
| DELETE | `/respondents/{id}` | GDPR hard-delete (audit-logged) |
| GET | `/analytics/{question_id}/clusters` | Semantic clusters of free-text answers (analytics extra required) |
| GET | `/webhooks` | List registered webhooks |
| POST | `/webhooks` | Register a webhook URL |
| DELETE | `/webhooks/{id}` | Remove a webhook |

---

## Layout

```
questionnaire/
  domain/
    types.py          # Question, AnswerValue, Template, Questionnaire — Pydantic discriminated unions
    expression.py     # Tiny AST + evaluator for follow-up conditions
    flow.py           # resolve_active_questions, next_unanswered_question
    validation.py     # validate_template, validate_answers, validate_for_submission
    audit.py          # Hash-chained AuditEvent / AuditRecord
    encryption.py     # Fernet wrapper for PII answers
    filtering.py      # Filter types, parse_filters, in-memory apply_filters (kept for tests)
  persistence/
    models.py         # SQLAlchemy 2.x ORM models
    sql_store.py      # SqlStore — the active store
    migrate.py        # JSON → SQLite migration
    store.py          # Legacy JsonStore (kept for migration source)
  cli/
    main.py           # Typer entry; subcommand dispatch
    template_cmd.py   # qst template create-from-file / list / show / seed / ai-generate
    answer_cmd.py     # qst answer start / resume / show
    query_cmd.py      # qst list / qst export
    admin_cmd.py      # qst migrate / audit / gdpr / analytics / api / webhook
    prompt.py         # questionary helpers per question type
  api/
    app.py            # FastAPI factory + all routes
  analytics/
    embeddings.py     # Lazy sentence-transformers wrapper
    clustering.py     # HDBSCAN over the embeddings
  llm/
    generate.py       # AI template generation (Claude, adaptive thinking, retry loop)
    analyze.py        # AI response analysis (streaming narrative report)
tests/
  test_flow.py            # tree walker, original cases
  test_flow_with_expr.py  # tree walker with ExprFollowUp
  test_validation.py      # template + answer validation, number type
  test_filtering.py       # in-memory filter combination
  test_store.py           # legacy JsonStore (still readable)
  test_sql_store.py       # SqlStore CRUD, versioning, immutability, push-down filters, GDPR
  test_audit.py           # hash chain integrity + tamper detection
  test_encryption.py      # Fernet round-trip + key rotation behavior
  test_expression.py      # AST evaluation + JSON round-trip
  test_migrate.py         # JSON → SQLite fidelity
  test_api.py             # HTTP API end-to-end via TestClient
  test_new_features.py    # auth, pagination, webhooks, archive, stats, duplicate, 8 question types
```

Run all tests:

```bash
pytest                          # 158 tests (~30s — includes the doctor wrapper)
pytest -m "not slow"            # fast tests only (~5s) — the inner-loop subset
make verify                     # pytest + `qst doctor` together (one-shot gate)
bash check_cli.sh               # 53 bash CLI end-to-end checks with full log output
```

---

## What changed from v0.1 → v0.2 → v0.3

`v0.1` was a clean exercise: JSON file, in-memory filtering, CLI only.
`v0.2` lifted the codebase toward a sellable engine.
`v0.3` adds AI-powered authoring, more question types, and operational features.

| Theme | v0.1 → v0.3 |
|---|---|
| Storage | Single JSON file → SQLite via SQLAlchemy 2.x; Postgres URL is a 1-line swap |
| Filtering | O(N) full scan in Python → indexed SQL `EXISTS` per filter; AND/OR/NOT fold into one query |
| Follow-ups | Equality only → expression AST: `eq/ne/gt/lt/ge/le/in/contains/and/or/not`; legacy shapes still accepted |
| Question types | 5 → **8** (added `number`, `rating`, `email`) |
| Templates | Immutable single version → versioned; edits append, questionnaires reference their snapshot |
| Compliance | None → submission immutability, append-only audit log with hash chain, PII encryption, GDPR export/delete |
| Interface | CLI only → CLI + FastAPI HTTP API + OpenAPI docs |
| Auth | None → optional API key (`QST_API_KEYS`); `X-Actor` advisory header |
| Webhooks | None → HMAC-signed HTTP callbacks for submit and GDPR delete events |
| AI features | None → AI template generation + streaming response analysis (litellm, 100+ providers; adaptive thinking for Claude) |
| Seed templates | 2 → **6** (medical, travel, HR onboarding, product feedback, event registration, customer support) |
| Analytics | None → optional semantic clustering of free-text answers |
| Tests | 44 → **158** |

---

## Design decisions worth knowing

### Expression engine, not `eval`
Follow-up conditions are JSON-serializable AST nodes evaluated by a
hand-rolled walker. There is no `eval`, no `simpleeval`, no string
expression language. Type errors at evaluation time return False rather
than crash, so a malformed condition can't bring the resolver down — at
worst its follow-up just doesn't fire.

### Missing-value semantics (SQL-like)
`Var(question_id)` of an unanswered question evaluates to a sentinel that
makes comparisons return False, AND/OR treat it as falsy, and `NOT
missing` return True. This avoids surprising activations and matches the
intuition behind `WHERE x = ?` in SQL with a NULL `x`.

### Why a single "active question set" function
`resolve_active_questions` is called by the CLI (decide what to ask
next), the validator (decide what must be present for submission), and
the renderer (display in order). Bugs in tree walking would manifest in
all three; centralizing the logic also centralizes the test target.

### Inverted-index filtering via SQL
Single-select / multi-select answers are stored in a row-per-option
shape (`answers(questionnaire_id, question_id, option_index, value_text)`)
with an index on `(question_id, value_text)`. Each `--includes`
becomes a `WHERE EXISTS (...)`, each `--excludes` a `WHERE NOT EXISTS`.
`OrFilter` maps to `or_(EXISTS(...), ...)`, `NotFilter` to `not_(...)`,
all recursively composed by `_filter_to_clause`. At ~100k questionnaires,
filter latency moves from seconds to single-digit milliseconds.

### Versioning that doesn't break old data
Templates are append-only `(id, version)`. Each questionnaire snapshots
its `(template_id, template_version)` at creation time. Editing a
template never invalidates prior responses; old responses keep working
against the version they were anchored to.

### Submission immutability
`submitted_at` is the lock. The store refuses any `upsert_answer`,
`delete_answer`, or repeat-submit on a submitted questionnaire.

### Hash-chained audit log
Each row's `hash = SHA-256(prev_hash || canonical_json(payload))`.
Editing a payload without recomputing every subsequent row breaks
verification. Single-writer chain — fine for single-process CLI; in a
multi-writer Postgres setup we'd add an advisory lock.

### PII encryption: Fernet, key from env
`QST_PII_KEY` is a Fernet base64-urlsafe key. PII free-text answers are
encrypted at write, decrypted on read, and the ciphertext is never
logged. Key rotation and KMS integration are documented next-step work.

### AI generation: retry loop with error feedback
`generate_template` uses litellm (supporting 100+ providers via a uniform
interface) with a strict JSON schema in the system prompt. On JSON parse
failure or Pydantic validation error, the error is fed back into a
follow-up message and the model retries. After `max_retries` (default 2)
the function raises a `RuntimeError` with the last error. This handles
cases where the model adds markdown fences or minor schema deviations.
For Claude models, adaptive thinking is enabled automatically.

### Filters on PII / non-select questions
Includes/Excludes are restricted to single/multi-select at parse time —
trying to filter on a free-text or PII question is rejected with a clear
error, not silently ignored.

---

## Assumptions

1. **Question IDs are globally unique** across all templates and
   versions. The filter command targets a question by ID alone, so
   uniqueness keeps the CLI ergonomic.
2. **Date format is `YYYY-MM-DD`**. Real calendar dates only —
   `2024-02-30` rejected; `2024-02-29` (leap year) accepted.
3. **Single-select requires more than 2 options**, per the spec.
4. **Multi-select requires at least one selection** at answer time.
5. **`QST_PII_KEY`** is read first; if absent, a key is generated on
   first use and persisted to `data/.qst_pii.key` (gitignored,
   `chmod 0600`). For production, set the env var from your secret
   manager and don't rely on the file.
6. **`QST_API_KEYS`** is optional. When unset, the API is open. When
   set (comma-separated), all write endpoints require `X-API-Key`.
7. **`QST_LLM_API_KEY`** is required only for AI features (not needed for local models like Ollama). The engine
   runs fully without it; AI endpoints return 503 when the key is absent. Set `QST_LLM_MODEL` to choose the
   provider and model (default: `anthropic/claude-opus-4-7`).
8. **The `analytics` extra** is opt-in. Without it, the
   `/analytics/.../clusters` endpoint returns 503.

---

## Deliberately deferred (and why)

| Deferred | Why |
|---|---|
| Web UI | API + OpenAPI is the value here; UI is a separate skill and a separate effort |
| OAuth / RBAC | Real auth design wants a day on its own; the API key + audit-log foundation is in place |
| Multi-tenancy | Needs a workspace model first |
| Postgres-now | SQLite ships in this round; Postgres swap is a SQLAlchemy URL change |
| Background workers for embeddings | Inline embedding works at small scale; promote to a worker once volume warrants |
| Drag-drop visual template builder | High effort, low differentiation when JSON-via-API is so direct |
| KMS / key rotation | Single Fernet key in this round; envelope-encryption is the documented next step |
| Webhook retry with backoff | Delivery is fire-and-forget in this round; retry queue is the documented next step |

---

## What lights up next

1. **OAuth + tenancy** unlocks the real B-direction (compliance/intake
   for healthcare, fintech, legal): every audit row gets a real actor;
   workspaces partition data; per-tenant Fernet keys.
2. **Semantic clustering UI**: `GET /analytics/{q}/clusters` already
   returns clusters with exemplars — surfacing them in a small Svelte
   page would land the differentiating story.
3. **Postgres swap** for write-throughput beyond a single SQLite writer.
   The store interface and SQL are dialect-agnostic; this is mechanical.
4. **Property-based tests** (Hypothesis) on the validator and the
   expression evaluator — the kind of test that finds the bug we
   haven't thought of yet.
5. **Webhook retry queue** — reliable delivery with exponential backoff
   and a dead-letter store.
