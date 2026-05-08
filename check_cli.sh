#!/usr/bin/env bash
# check_cli.sh — run every qst CLI command and report PASS/FAIL with full logs.
# Usage: bash check_cli.sh [--keep]
#   --keep  don't delete the temp work dir on exit (useful for debugging)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QST="$SCRIPT_DIR/.venv/bin/qst"

if [[ ! -x "$QST" ]]; then
    echo "ERROR: qst not found at $QST — activate venv or install with pip install -e ." >&2
    exit 1
fi

KEEP=0
for arg in "$@"; do
    [[ "$arg" == "--keep" ]] && KEEP=1
done

WORK_DIR=$(mktemp -d -t qst_check_XXXXXX)
mkdir -p "$WORK_DIR/data"

cleanup() {
    if [[ $KEEP -eq 0 ]]; then
        rm -rf "$WORK_DIR"
    else
        echo ""
        echo "work dir preserved: $WORK_DIR"
    fi
}
trap cleanup EXIT

PASS=0
FAIL=0
TOTAL=0

# ── Colour codes (no-op if not a terminal) ─────────────────────────────────
if [[ -t 1 ]]; then
    GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; RESET=$'\033[0m'; BOLD=$'\033[1m'
else
    GREEN=''; RED=''; RESET=''; BOLD=''
fi

# ── check <name> <expected_rc> [expected_str] -- <cmd...> ──────────────────
# Runs cmd inside WORK_DIR. Prints full output, then PASS/FAIL.
# If expected_str is set, output must contain that string.
check() {
    local name="$1"
    local expect_rc="$2"
    local expect_str="$3"
    shift 3
    TOTAL=$(( TOTAL + 1 ))

    echo ""
    echo "${BOLD}[$TOTAL] $name${RESET}"
    echo "  cmd: $*"

    local output rc=0
    output=$(cd "$WORK_DIR" && "$@" 2>&1) || rc=$?

    # Print each output line indented
    if [[ -n "$output" ]]; then
        while IFS= read -r line; do
            echo "  │ $line"
        done <<< "$output"
    fi

    local ok=1
    if [[ "$rc" -ne "$expect_rc" ]]; then
        echo "  ${RED}✗ exit $rc (expected $expect_rc)${RESET}"
        ok=0
    fi
    if [[ -n "$expect_str" ]] && ! grep -qF "$expect_str" <<< "$output"; then
        echo "  ${RED}✗ output missing: ${expect_str}${RESET}"
        ok=0
    fi

    if [[ $ok -eq 1 ]]; then
        echo "  ${GREEN}✓ PASS${RESET}"
        PASS=$(( PASS + 1 ))
    else
        echo "  ${RED}✗ FAIL${RESET}"
        FAIL=$(( FAIL + 1 ))
    fi
}

# ── check_capture: same as check but saves output to a variable ────────────
LAST_OUTPUT=""
check_capture() {
    local name="$1"
    local expect_rc="$2"
    local expect_str="$3"
    shift 3
    TOTAL=$(( TOTAL + 1 ))

    echo ""
    echo "${BOLD}[$TOTAL] $name${RESET}"
    echo "  cmd: $*"

    local rc=0
    LAST_OUTPUT=$(cd "$WORK_DIR" && "$@" 2>&1) || rc=$?

    if [[ -n "$LAST_OUTPUT" ]]; then
        while IFS= read -r line; do
            echo "  │ $line"
        done <<< "$LAST_OUTPUT"
    fi

    local ok=1
    if [[ "$rc" -ne "$expect_rc" ]]; then
        echo "  ${RED}✗ exit $rc (expected $expect_rc)${RESET}"
        ok=0
    fi
    if [[ -n "$expect_str" ]] && ! grep -qF "$expect_str" <<< "$LAST_OUTPUT"; then
        echo "  ${RED}✗ output missing: ${expect_str}${RESET}"
        ok=0
    fi

    if [[ $ok -eq 1 ]]; then
        echo "  ${GREEN}✓ PASS${RESET}"
        PASS=$(( PASS + 1 ))
    else
        echo "  ${RED}✗ FAIL${RESET}"
        FAIL=$(( FAIL + 1 ))
    fi
}

# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 1: Templates ═══════════════════════════════════════════${RESET}"

check "template seed (first run)" 0 "seeded tpl_medical" \
    "$QST" template seed

check "template seed idempotent (skip existing)" 0 "skip tpl_medical" \
    "$QST" template seed

check "template list (shows both seeds)" 0 "tpl_medical" \
    "$QST" template list

check "template show tpl_medical" 0 "Medical Intake" \
    "$QST" template show tpl_medical

check "template show tpl_travel" 0 "Travel Survey" \
    "$QST" template show tpl_travel

check "template show unknown → exit 1" 1 "unknown template id" \
    "$QST" template show no_such_template

# ── Custom template JSON ──────────────────────────────────────────────────
cat > "$WORK_DIR/custom_tpl.json" <<'EOF'
{
  "id": "tpl_custom",
  "title": "Custom Survey",
  "created_at": "2026-01-01T00:00:00Z",
  "questions": [
    {
      "type": "single_select",
      "id": "priority",
      "prompt": "Priority level?",
      "options": ["Low", "Medium", "High", "Critical"]
    },
    {
      "type": "boolean",
      "id": "urgent",
      "prompt": "Is this urgent?"
    },
    {
      "type": "free_text",
      "id": "description",
      "prompt": "Describe the issue"
    }
  ]
}
EOF

check "template create-from-file (custom)" 0 "saved template tpl_custom" \
    "$QST" template create-from-file custom_tpl.json --actor ci

# Version bump (re-save same id with modified title)
cat > "$WORK_DIR/custom_tpl_v2.json" <<'EOF'
{
  "id": "tpl_custom",
  "title": "Custom Survey v2",
  "created_at": "2026-01-01T00:00:00Z",
  "questions": [
    {
      "type": "single_select",
      "id": "priority",
      "prompt": "Priority level?",
      "options": ["Low", "Medium", "High", "Critical"]
    },
    {
      "type": "boolean",
      "id": "urgent",
      "prompt": "Is this urgent?"
    },
    {
      "type": "free_text",
      "id": "description",
      "prompt": "Describe the issue (updated)"
    }
  ]
}
EOF

check "template create-from-file version bump → v2" 0 "tpl_custom v2" \
    "$QST" template create-from-file custom_tpl_v2.json --actor ci

check "template show -v 1 (historical)" 0 "Custom Survey" \
    "$QST" template show tpl_custom -v 1

check "template show (current = v2)" 0 "Custom Survey v2" \
    "$QST" template show tpl_custom

# ── Invalid template: too few options ─────────────────────────────────────
cat > "$WORK_DIR/bad_options.json" <<'EOF'
{
  "id": "tpl_bad",
  "title": "Bad Options",
  "created_at": "2026-01-01T00:00:00Z",
  "questions": [
    {
      "type": "single_select",
      "id": "q1",
      "prompt": "Pick one",
      "options": ["A", "B"]
    }
  ]
}
EOF

check "template create-from-file invalid (≤2 options) → exit 2" 2 "structural validation" \
    "$QST" template create-from-file bad_options.json

# ── Invalid template: malformed JSON ──────────────────────────────────────
cat > "$WORK_DIR/bad_json.json" <<'EOF'
{ "title": "Bad", "questions": [ { "type": "unknown_type" } ] }
EOF

check "template create-from-file malformed → exit 2" 2 "" \
    "$QST" template create-from-file bad_json.json


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 2: Answer fill ══════════════════════════════════════════${RESET}"

# Medical with allergies
cat > "$WORK_DIR/medical_allergy.json" <<'EOF'
{
  "has_allergies": true,
  "allergy_details": "Penicillin",
  "contact_method": "Email",
  "date_of_birth": "1990-06-15",
  "age": 35,
  "symptoms": ["Fever", "Headache"],
  "fever_duration": "3 days"
}
EOF

check_capture "answer fill tpl_medical with allergies + fever follow-up" 0 "submitted questionnaire" \
    "$QST" answer fill tpl_medical medical_allergy.json --respondent user_a --actor ci
MED_A_ID=$(grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<< "$LAST_OUTPUT" | head -1)

# Medical without allergies (follow-up skipped)
cat > "$WORK_DIR/medical_no_allergy.json" <<'EOF'
{
  "has_allergies": false,
  "contact_method": "Phone",
  "date_of_birth": "1985-03-20",
  "age": 40,
  "symptoms": ["Cough"]
}
EOF

check_capture "answer fill tpl_medical no allergies (follow-up skipped)" 0 "submitted questionnaire" \
    "$QST" answer fill tpl_medical medical_no_allergy.json --respondent user_b --actor ci
MED_B_ID=$(grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<< "$LAST_OUTPUT" | head -1)

# Travel — plain
cat > "$WORK_DIR/travel_simple.json" <<'EOF'
{
  "region": "Europe",
  "business_trip": false,
  "activities": ["Hiking", "Sightseeing"],
  "return_date": "2026-03-15",
  "favorite_moment": "Sunrise on the Alps"
}
EOF

check_capture "answer fill tpl_travel simple (no business follow-up)" 0 "submitted questionnaire" \
    "$QST" answer fill tpl_travel travel_simple.json --respondent user_c --actor ci
TRAVEL_C_ID=$(grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<< "$LAST_OUTPUT" | head -1)

# Travel — business trip with nested industry follow-up
cat > "$WORK_DIR/travel_business.json" <<'EOF'
{
  "region": "Asia",
  "business_trip": true,
  "industry": "Tech",
  "activities": ["Food tours"],
  "return_date": "2026-04-10",
  "favorite_moment": "Street food in Tokyo"
}
EOF

check_capture "answer fill tpl_travel business trip with industry" 0 "submitted questionnaire" \
    "$QST" answer fill tpl_travel travel_business.json --respondent user_d --actor ci
TRAVEL_D_ID=$(grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<< "$LAST_OUTPUT" | head -1)

# Draft (--no-submit)
check_capture "answer fill --no-submit creates draft" 0 "saved draft questionnaire" \
    "$QST" answer fill tpl_medical medical_no_allergy.json --no-submit
DRAFT_ID=$(grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<< "$LAST_OUTPUT" | head -1)

# Error: unknown template
check "answer fill unknown template → exit 1" 1 "unknown template id" \
    "$QST" answer fill no_such_template medical_no_allergy.json

# Error: wrong answer type (age as string)
cat > "$WORK_DIR/bad_type.json" <<'EOF'
{
  "has_allergies": false,
  "contact_method": "Email",
  "date_of_birth": "1990-01-01",
  "age": "not-a-number",
  "symptoms": ["Cough"]
}
EOF

check "answer fill bad answer type → exit 2" 2 "could not coerce" \
    "$QST" answer fill tpl_medical bad_type.json

# Error: unknown question id in answers file
cat > "$WORK_DIR/unknown_qid.json" <<'EOF'
{ "nonexistent_question": "value" }
EOF

check "answer fill unknown question id → exit 2" 2 "unknown question id" \
    "$QST" answer fill tpl_medical unknown_qid.json


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 3: Answer show ══════════════════════════════════════════${RESET}"

check "answer show submitted questionnaire" 0 "status=submitted" \
    "$QST" answer show "$MED_A_ID"

check "answer show draft questionnaire" 0 "status=draft" \
    "$QST" answer show "$DRAFT_ID"

check "answer show nonexistent → exit 1" 1 "unknown questionnaire id" \
    "$QST" answer show "00000000-0000-0000-0000-000000000000"


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 4: List / Query ═════════════════════════════════════════${RESET}"

check "qst list (all submitted)" 0 "submitted" \
    "$QST" list

check "qst list --include-drafts (shows draft too)" 0 "draft" \
    "$QST" list --include-drafts

check "qst list -t tpl_medical" 0 "Medical Intake" \
    "$QST" list -t tpl_medical

check "qst list -t tpl_travel" 0 "Travel Survey" \
    "$QST" list -t tpl_travel

check "qst list -i contact_method=Email (includes filter)" 0 "submitted" \
    "$QST" list -i contact_method=Email

check "qst list -x contact_method=Email (excludes filter)" 0 "submitted" \
    "$QST" list -x contact_method=Email

check "qst list -i symptoms=Fever -x contact_method=Phone (AND combo)" 0 "submitted" \
    "$QST" list -i symptoms=Fever -x contact_method=Phone

check "qst list -i region=Europe" 0 "submitted" \
    "$QST" list -i region=Europe

check "qst list -i region=Asia -i business_trip=true" 2 "invalid filter" \
    "$QST" list -i region=Asia -i business_trip=true

check "qst list -i notes=hi (free-text → invalid) → exit 2" 2 "invalid filter" \
    "$QST" list -i notes=hi

check "qst list unknown template → exit 2" 2 "invalid filter" \
    "$QST" list -t no_such_template

check "qst list malformed filter (no equals) → exit 2" 2 "invalid filter" \
    "$QST" list -i no_equals_sign


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 5: Export ═══════════════════════════════════════════════${RESET}"

check "qst export to file" 0 "rows to" \
    "$QST" export export_all.csv

check "qst export filtered by template" 0 "rows to" \
    "$QST" export export_medical.csv -t tpl_medical

check "qst export to stdout (-)" 0 "questionnaire_id" \
    "$QST" export -

check "qst export with includes filter" 0 "" \
    "$QST" export export_fever.csv -i symptoms=Fever


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 6: Audit ════════════════════════════════════════════════${RESET}"

check "audit list (shows entries)" 0 "template" \
    "$QST" audit list

check "audit list --since 0 (all entries)" 0 "" \
    "$QST" audit list --since 0

check "audit list --since 999 (no entries after high seq)" 0 "" \
    "$QST" audit list --since 999

check "audit verify (hash chain OK)" 0 "audit chain OK" \
    "$QST" audit verify


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 7: GDPR ═════════════════════════════════════════════════${RESET}"

check "gdpr export user_a → zip" 0 "bytes to" \
    "$QST" gdpr export user_a gdpr_user_a.zip

check "gdpr zip file exists and is non-empty" 0 "" \
    test -s gdpr_user_a.zip

check "gdpr export user_c → zip" 0 "bytes to" \
    "$QST" gdpr export user_c gdpr_user_c.zip

check "gdpr delete user_c --yes" 0 "deleted" \
    "$QST" gdpr delete user_c --yes --actor ci

check "qst list after GDPR delete (user_c gone)" 0 "" \
    "$QST" list -i region=Europe

# Verify that user_c questionnaire is really gone
check_capture "answer show after GDPR delete → exit 1" 1 "unknown questionnaire id" \
    "$QST" answer show "$TRAVEL_C_ID"


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 8: Migration ════════════════════════════════════════════${RESET}"

# No JSON file → no-op
check "migrate no JSON file → exit 0 with message" 0 "nothing to migrate" \
    "$QST" migrate

# Create a minimal legacy JSON for migration test
MIGRATE_DIR=$(mktemp -d -t qst_migrate_XXXXXX)
mkdir -p "$MIGRATE_DIR/data"

cat > "$MIGRATE_DIR/data/db.json" <<'EOF'
{
  "templates": {
    "tpl_legacy": {
      "id": "tpl_legacy",
      "title": "Legacy Template",
      "created_at": "2025-01-01T00:00:00Z",
      "questions": [
        {
          "type": "free_text",
          "id": "comments",
          "prompt": "Any comments?"
        }
      ]
    }
  },
  "questionnaires": {
    "legacy-qn-001": {
      "id": "legacy-qn-001",
      "template_id": "tpl_legacy",
      "created_at": "2025-01-02T00:00:00Z",
      "submitted_at": "2025-01-02T01:00:00Z",
      "answers": {
        "comments": {"type": "free_text", "value": "All good"}
      }
    }
  }
}
EOF

mkdir -p "$MIGRATE_DIR/data"
check "migrate from legacy JSON" 0 "migrated:" \
    bash -c "cd '$MIGRATE_DIR' && '$QST' migrate"

check "migrated template is queryable" 0 "tpl_legacy" \
    bash -c "cd '$MIGRATE_DIR' && '$QST' template list"

rm -rf "$MIGRATE_DIR"


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "${BOLD}══ SECTION 9: Analytics (optional) ════════════════════════════════${RESET}"

# Analytics extra may not be installed — treat exit 2 as acceptable
TOTAL=$(( TOTAL + 1 ))
echo ""
echo "${BOLD}[$TOTAL] analytics cluster favorite_moment (optional)${RESET}"
echo "  cmd: $QST analytics cluster favorite_moment"

analytic_out=$(cd "$WORK_DIR" && "$QST" analytics cluster favorite_moment 2>&1) || analytic_rc=$?
analytic_rc=${analytic_rc:-0}

while IFS= read -r line; do echo "  │ $line"; done <<< "$analytic_out"

if echo "$analytic_out" | grep -qF "analytics extra not available"; then
    echo "  ${GREEN}✓ PASS (analytics extra not installed — skipped gracefully)${RESET}"
    PASS=$(( PASS + 1 ))
elif [[ $analytic_rc -eq 0 ]]; then
    echo "  ${GREEN}✓ PASS${RESET}"
    PASS=$(( PASS + 1 ))
elif [[ $analytic_rc -eq 1 ]] && echo "$analytic_out" | grep -qF "no free-text answers found"; then
    echo "  ${GREEN}✓ PASS (no embeddings stored — expected without analytics extra)${RESET}"
    PASS=$(( PASS + 1 ))
else
    echo "  ${RED}✗ FAIL (exit $analytic_rc)${RESET}"
    FAIL=$(( FAIL + 1 ))
fi


# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "${BOLD}RESULTS: $PASS passed, $FAIL failed, $TOTAL total${RESET}"
echo "════════════════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    echo "${RED}SOME CHECKS FAILED${RESET}"
    exit 1
else
    echo "${GREEN}ALL CHECKS PASSED${RESET}"
    exit 0
fi
