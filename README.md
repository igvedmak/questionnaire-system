# Questionnaire System

A small CLI for defining questionnaire templates, answering them, and querying
the resulting submissions.

Implements the full home-assignment spec: five question types, recursive
follow-up questions, type-aware answer validation, JSON persistence between
runs, and AND-combined filtering of submitted questionnaires.

---

## Run

Requires Python 3.11+.

```bash
# Install (with `uv`, recommended)
uv venv
uv pip install -e ".[dev]"

# Or with stdlib venv + pip
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Activate so `qst` is on PATH
source .venv/bin/activate
```

A 30-second tour:

```bash
qst template seed                      # load two demo templates
qst template list
qst template show tpl_medical

qst answer start tpl_medical           # interactive — prompts you per question;
                                       # follow-ups appear as their triggers fire

qst list                               # all submitted questionnaires
qst list -t tpl_medical                # filter by template
qst list -i contact_method=Email       # AND filter: includes
qst list -i contact_method=Email \
         -i symptoms=Fever \
         -x activities=Beach           # AND of all three
qst answer show <questionnaire_id>     # detailed view
```

Data lives in `./data/db.json` (relative to wherever you run `qst`). Delete
the file to reset.

---

## Run the tests

```bash
.venv/bin/pytest
```

44 tests covering the four modules below. Run in ~0.3s.

---

## Layout

```
questionnaire/
  domain/
    types.py        # Pydantic discriminated unions: Question, AnswerValue,
                    # Template, Questionnaire, Database
    flow.py         # resolve_active_questions: walks the template tree,
                    # producing the ordered list of currently-active questions
    validation.py   # validate_template (structural rules) and
                    # validate_answers / validate_for_submission
    filtering.py    # apply_filters + parse_filters (CLI string → typed Filter)
  persistence/
    store.py        # atomic JSON-file store
  cli/
    main.py         # Typer entry point
    template_cmd.py # template create-from-file / list / show / seed
    answer_cmd.py   # answer start / resume / show; the interactive loop
    query_cmd.py    # qst list (with --template / --includes / --excludes)
    prompt.py       # one questionary helper per question type
tests/
  test_flow.py
  test_validation.py
  test_filtering.py
  test_store.py
```

---

## Key design decisions

### 1. Questions are a discriminated union, follow-ups make a recursive tree

Five concrete question classes (Boolean, SingleSelect, MultiSelect, Date,
FreeText) are united via `Annotated[Union[...], Field(discriminator="type")]`.
Pydantic v2 round-trips this to/from JSON natively — no custom deserializer.

The three branchable types carry `follow_ups: list[FollowUp]`, where each
follow-up holds `questions: list[Question]`. Pydantic resolves the forward
reference, so the tree can nest arbitrarily deep.

The type system enforces that date and free-text questions cannot have
follow-ups — a structural error in JSON would be a Pydantic parse error,
not a runtime surprise.

### 2. One function answers "which questions are active right now"

`resolve_active_questions(template_questions, answers)` is the single source
of truth for tree-walking. It's called by:

- the interactive CLI loop (to decide what to prompt next),
- `validate_for_submission` (to know what must be answered),
- `qst answer show` (to render in a sensible order).

Bugs in tree walking would manifest in all three — making this one function
the highest-leverage test target. See [tests/test_flow.py](tests/test_flow.py).

### 3. Follow-up triggers are JSON-serializable predicates

Two trigger shapes:

- `BoolFollowUp(when_equals: bool)` — for boolean questions
- `SelectFollowUp(when_option_selected: str)` — for both single- and
  multi-select. For single-select, "selected" means the chosen option
  equals the trigger value. For multi-select, "selected" means the trigger
  value is among the chosen options. Same predicate; the evaluator branches
  on the answer type.

No closures, no expression strings — predicates round-trip through JSON cleanly.

### 4. Filters: AND combined, includes/excludes restricted to select questions

`Filter` is `TemplateFilter | IncludesFilter | ExcludesFilter`. Filters are
parsed from CLI strings into typed objects; an includes/excludes filter
targeting a non-select question is rejected at parse time with a clear
error, rather than silently matching nothing.

Edge case decision: when a filter targets a question that the questionnaire
never reached (because a follow-up never triggered), `IncludesFilter` returns
False and `ExcludesFilter` returns True. This matches the natural English
reading: "questionnaire X excludes value Y" is true if X never had a chance
to include Y in the first place. Tested in
[tests/test_filtering.py](tests/test_filtering.py).

### 5. Drafts are persisted; only submitted questionnaires appear in `qst list`

The interactive answering flow saves after every answer, so a Ctrl-C never
loses progress. `qst answer resume <id>` picks up where you left off.
By default `qst list` shows only submitted questionnaires; use
`--include-drafts` to see in-progress ones.

### 6. The orphaned-answer trap

If a user answers a follow-up question, then changes the parent answer so
the trigger no longer fires, the follow-up's answer becomes "orphaned":
present in the answers map but pointing at an inactive question. Validation
catches this and reports it. The interactive flow doesn't currently allow
re-answering a previous question (would need a "back" affordance), but the
domain layer is correct for it.

### 7. Question IDs are globally unique across all templates

The filter command targets a question by ID alone (`--includes color=red`).
For that to be unambiguous, IDs must be globally unique, not just unique
within a template. `qst template create-from-file` rejects collisions at
load time.

### 8. Persistence is a single JSON file, written atomically

Atomic writes via tmp-file + `os.replace` guarantee the DB is never
half-written even on a crash. No DB, no migrations, no concurrency control —
this is a single-process CLI.

### 9. What I deliberately did **not** build

- web UI / REST API
- multi-user concurrency or file locking
- template editing or deletion
- schema versioning
- internationalization

These are real concerns for a real system, but each would have added more
code than the entire domain layer combined and obscured what the spec was
actually asking for.

---

## Assumptions

1. **Templates are immutable once created.** The spec says this for
   questionnaires; I extended it to templates for simplicity (no
   `template edit` command).
2. **Date format is `YYYY-MM-DD`.** Real calendar date, no time, no
   timezone. `2024-02-30` is rejected; `2024-02-29` (leap year) is accepted.
3. **Single-select requires more than 2 options** (per spec wording).
   Enforced in `validate_template`.
4. **Multi-select requires at least one selection at answer time.**
5. **Filter values are compared as case-sensitive strings** that exactly
   match option strings.
6. **Question IDs are globally unique.** See decision #7 above.
7. **`excludes` matches questionnaires where the question was never reached.**
   See decision #4 above.

---

## What's in the tests

44 tests, organized by module:

**`test_flow.py`** — the tree walker:
- top-level questions only, no follow-ups
- follow-up triggered / not triggered (boolean, single-select)
- nested follow-ups (depth 2) including the "flip parent → subtree collapses" case
- multi-select where multiple chosen options each trigger different follow-ups
- `next_unanswered_question` skipping answered and inactive questions

**`test_validation.py`** — both layers of validation:
- template structure: option count, duplicate IDs, follow-up triggers
  pointing at non-existent options
- answer correctness: type mismatch, single-select wrong option,
  multi-select empty/duplicates/invalid options
- date format: parametrized over `2024-02-30`, `2025-13-01`, `2024-02-29`,
  `not-a-date`, `2025/01/01`, etc.
- the orphaned-answer case (parent flipped after follow-up was answered)
- submission requires all active questions, but does NOT require inactive ones

**`test_filtering.py`** — the query layer:
- template filter, includes/excludes on single-select and multi-select
- the "question not reached" edge case (decision #4)
- AND combination of three filters
- `parse_filters` rejection of: non-select target, unknown question,
  unknown template, malformed `key=value`
- `parse_filters` finds questions nested inside follow-ups

**`test_store.py`** — persistence:
- empty/missing/blank file → empty Database
- full round-trip preserves the entire DB structurally
- atomic write leaves no `.tmp` file behind
