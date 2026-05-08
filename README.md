# Questionnaire Engine

A programmable questionnaire engine — templates with expression-based
follow-ups, instances answered through a CLI or HTTP API, indexed
filtering, tamper-evident audit log, encrypted PII fields, GDPR
export/delete, and semantic clustering of free-text answers.

Implements the original home-assignment spec in full and extends it
toward a credible product foundation.

---

## Highlights

| Feature | Where |
|---|---|
| 6 question types: boolean, single-select, multi-select, date, free-text, **number** | `domain/types.py` |
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
| **CSV export** of filtered queries, streamed | `cli/query_cmd.py`, `/questionnaires.csv` |
| **Semantic free-text clustering** (HDBSCAN over sentence-transformer embeddings) — optional analytics extra | `analytics/clustering.py` |
| **Migration** from the legacy JSON store via `qst migrate` | `persistence/migrate.py` |
| **OR / NOT filter combinators**: `OrFilter(filters=[...])` and `NotFilter(inner=...)` nest inside the flat AND list | `domain/filtering.py` |
| **118 tests** covering domain, store, audit, encryption, expression engine, migration, API, and one end-to-end `qst doctor` wrapper | `tests/` |
| **`qst doctor`** — 124 checks across 11 sections (types, expressions, filters, lifecycle, audit, GDPR, versioning, validation, migration, HTTP API, analytics); exits 0/1 | `cli/doctor_cmd.py` |
| **`check_cli.sh`** — 53 bash end-to-end checks with full log output per command; `bash check_cli.sh` | `check_cli.sh` |
| **`qst answer fill`** — non-interactive submission from a JSON file (CI / agents) | `cli/answer_cmd.py` |
| **`Makefile`** — one-shot `make install` / `make verify` / `make demo` | top-level |

---

## Run

Requires Python 3.11+.

**One-shot setup** (no manual env work, no extra installs):

```bash
make install      # creates venv, installs core + dev + analytics extras
make verify       # runs pytest then `qst doctor` (full end-to-end self-test)
```

If you don't have `make`, the same steps directly:

```bash
uv venv && uv pip install -e ".[dev,analytics]"   # or python3 -m venv + pip
source .venv/bin/activate
pytest && qst doctor
```

`qst doctor` is the single source of truth that the system works:
124 checks across 11 sections — question types, expression engine, filter
combinators, submission lifecycle, audit & security, GDPR, template
versioning, validation errors, migration, HTTP API, and (if the analytics
extra is installed) real semantic clustering on sentence-transformer embeddings.

**PII encryption key.** Zero setup needed locally — the engine generates
a key on first use and persists it to `data/.qst_pii.key` (gitignored,
`chmod 0600`). The env var `QST_PII_KEY` always wins over the file; in
production, set it from your secret manager. Key rotation / KMS
integration is documented next-step work.

A 60-second tour:

```bash
qst doctor                           # end-to-end self-test (124 checks / 11 sections)

qst template seed                    # two demo templates with PII + nested follow-ups
qst template list                    # current versions
qst template show tpl_medical -v 1   # specific version

qst answer start tpl_medical \
    --respondent alice               # interactive; follow-ups appear as triggers fire
qst answer resume <questionnaire_id> # pick up a draft

# Non-interactive answering (CI / scripts / agents):
echo '{"has_allergies":true,"allergy_details":"seeds","contact_method":"Email",
       "date_of_birth":"1991-11-13","age":33,"symptoms":["Fever","Headache"],
       "fever_duration":"2 days"}' > /tmp/answers.json
qst answer fill tpl_medical /tmp/answers.json --respondent alice

qst list                             # submitted questionnaires
qst list -t tpl_medical \
        -i contact_method=Email \
        -i symptoms=Fever            # AND of three filters (OR/NOT via API/SDK)

qst export submissions.csv -t tpl_medical

qst audit list                       # every state change
qst audit verify                     # SHA-256 chain integrity check

qst gdpr export alice alice.zip      # all of alice's submissions
qst gdpr delete alice --yes          # permanent, audit-logged

qst api --port 8000                  # HTTP API + /docs (OpenAPI)
```

```bash
# Migrate from the legacy JSON store (data/db.json) into SQLite (data/db.sqlite):
qst migrate
```

---

## HTTP API

Boot:

```bash
qst api --host 0.0.0.0 --port 8000
# OpenAPI: http://localhost:8000/docs
```

Endpoints:

| Method | Path | Notes |
|---|---|---|
| POST | `/templates` | New template (auto v1) or new version (if id is reused) |
| GET | `/templates` | List current versions |
| GET | `/templates/{id}` | `?version=` for a specific version |
| GET | `/templates/{id}/versions` | All versions |
| POST | `/questionnaires` | Start an instance |
| GET | `/questionnaires/{id}` | Get with answers |
| GET | `/questionnaires` | Filter via `?template=`, `?includes=qid=val`, `?excludes=qid=val`, `?include_drafts=` |
| PUT | `/questionnaires/{id}/answers/{qid}` | Upsert one answer (rejected with 409 after submit) |
| DELETE | `/questionnaires/{id}/answers/{qid}` | Remove one answer (rejected with 409 after submit) |
| POST | `/questionnaires/{id}/submit` | Lock the questionnaire |
| GET | `/questionnaires.csv` | Streaming CSV of the filtered set |
| GET | `/audit?since=<seq>` | Audit log entries |
| POST | `/audit/verify` | Recompute the chain, 200 OK or 409 |
| GET | `/respondents/{id}/export` | GDPR zip |
| DELETE | `/respondents/{id}` | GDPR hard-delete (audit-logged) |
| GET | `/analytics/{question_id}/clusters` | Semantic clusters of free-text answers (analytics extra required) |

The `X-Actor` header (when present) is recorded in the audit log for every
state-changing request. **No auth in this round** — the documented next
step.

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
    template_cmd.py   # qst template create-from-file / list / show / seed
    answer_cmd.py     # qst answer start / resume / show
    query_cmd.py      # qst list / qst export
    admin_cmd.py      # qst migrate / audit / gdpr / analytics / api
    prompt.py         # questionary helpers per question type
  api/
    app.py            # FastAPI factory + all routes
  analytics/
    embeddings.py     # Lazy sentence-transformers wrapper
    clustering.py     # HDBSCAN over the embeddings
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
```

Run all tests:

```bash
pytest                          # 118 tests (~20s — includes the doctor wrapper)
pytest -m "not slow"            # 117 fast tests (~5s) — the inner-loop subset
make verify                     # pytest + `qst doctor` together (one-shot gate)
bash check_cli.sh               # 53 bash CLI end-to-end checks with full log output
```

---

## What changed from v0.1 (the original assignment)

`v0.1` was a clean exercise: JSON file, in-memory filtering, CLI only.
`v0.2` keeps every previous test passing and lifts the codebase toward a
sellable engine.

| Theme | v0.1 → v0.2 |
|---|---|
| Storage | Single JSON file → SQLite via SQLAlchemy 2.x; Postgres URL is a 1-line swap |
| Filtering | O(N) full scan in Python → indexed SQL `EXISTS` per filter; AND/OR/NOT fold into one query; `OrFilter`/`NotFilter` added |
| Follow-ups | Equality only (`when_equals`, `when_option_selected`) → expression AST: `eq/ne/gt/lt/ge/le/in/contains/and/or/not` referencing any answer; legacy shapes still accepted |
| Question types | 5 → 6 (added `number` with `min`/`max`/`integer`) |
| Templates | Immutable single version → versioned (edits append, questionnaires reference their snapshot) |
| Compliance | None → submission immutability, append-only audit log with hash chain, PII encryption at rest, GDPR export/delete |
| Interface | CLI only → CLI + FastAPI HTTP API |
| Analytics | None → optional semantic clustering of free-text answers |
| Tests | 44 → 118 |

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
all recursively composed by `_filter_to_clause`. The flat AND list,
plus OR/NOT nesting, all fold into a single SQL query.
At ~100k questionnaires, filter latency moves from seconds to single-digit
milliseconds.

### Versioning that doesn't break old data
Templates are append-only `(id, version)`. Each questionnaire snapshots
its `(template_id, template_version)` at creation time. Editing a
template never invalidates prior responses; old responses keep working
against the version they were anchored to.

### Submission immutability
`submitted_at` is the lock. The store refuses any `upsert_answer`,
`delete_answer`, or repeat-submit on a submitted questionnaire. Edits
go through a controlled "amend" path that doesn't exist yet — keeps the
audit trail clean.

### Hash-chained audit log
Each row's `hash = SHA-256(prev_hash || canonical_json(payload))`.
Editing a payload without recomputing every subsequent row breaks
verification. Single-writer chain — fine for single-process CLI; in a
multi-writer Postgres setup we'd add an advisory lock.

### PII encryption: Fernet, key from env
`QST_PII_KEY` is a Fernet base64-urlsafe key. PII free-text answers are
encrypted at write, decrypted on read, and the ciphertext is never
logged. Key rotation and KMS integration are documented next-step work
(out of scope for this round).

### Filters on PII / non-select questions
Includes/Excludes are restricted to single/multi-select at parse time —
trying to filter on a free-text or PII question is rejected with a clear
error, not silently ignored.

### Excludes-when-not-reached
When a follow-up never triggers and so the targeted question wasn't
even asked, `IncludesFilter` returns False and `ExcludesFilter` returns
True. This matches the natural English reading and is tested.

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
6. **No auth in this round**. The `X-Actor` header is advisory and
   recorded in the audit log; it is not authenticated.
7. **The `analytics` extra** is opt-in. Without it, the
   `/analytics/.../clusters` endpoint returns 503 and embeddings are
   skipped on submit.

---

## Deliberately deferred (and why)

| Deferred | Why |
|---|---|
| Web UI | API + OpenAPI is the value here; UI is a separate skill and a separate effort |
| Auth (OAuth, API keys, RBAC) | Real auth design wants a day on its own; the audit-log foundation is in place |
| Multi-tenancy | Same — needs a workspace model first |
| Postgres-now | SQLite ships in this round; Postgres swap is a SQLAlchemy URL change |
| Background workers for embeddings | Inline embedding works at small scale; promote to a worker once volume warrants |
| Drag-drop visual template builder | High effort, low differentiation when JSON-via-API is so direct |
| KMS / key rotation | Single Fernet key in this round; envelope-encryption is the documented next step |
| Webhooks | A day on retry/security/HMAC by itself; out of scope |

---

## What lights up next

1. **Auth + tenancy** unlocks the real B-direction (compliance/intake
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
