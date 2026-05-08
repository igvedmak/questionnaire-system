import { describe, it, expect } from 'vitest'
import { resolveActiveQuestions, getFollowUpChildren } from './followups'
import type {
  AnswerValue, BooleanQuestion, SingleSelectQuestion,
  MultiSelectQuestion, NumberQuestion, Question,
} from '../types'

// ── helpers ──────────────────────────────────────────────────────────────────

function boolQ(id: string, followUps: BooleanQuestion['follow_ups'] = []): BooleanQuestion {
  return { type: 'boolean', id, prompt: id, pii: false, required: true, follow_ups: followUps }
}

function singleQ(id: string, options: string[], followUps: SingleSelectQuestion['follow_ups'] = []): SingleSelectQuestion {
  return { type: 'single_select', id, prompt: id, pii: false, required: true, options, follow_ups: followUps }
}

function multiQ(id: string, options: string[], followUps: MultiSelectQuestion['follow_ups'] = []): MultiSelectQuestion {
  return { type: 'multi_select', id, prompt: id, pii: false, required: true, options, follow_ups: followUps }
}

function numQ(id: string, followUps: NumberQuestion['follow_ups'] = []): NumberQuestion {
  return { type: 'number', id, prompt: id, pii: false, required: true, min: null, max: null, integer: false, follow_ups: followUps }
}

function freeQ(id: string): Question {
  return { type: 'free_text', id, prompt: id, pii: false, required: true }
}

function ans<T extends AnswerValue>(v: T): T { return v }

// ── resolveActiveQuestions ────────────────────────────────────────────────────

describe('resolveActiveQuestions — flat list', () => {
  it('returns all top-level questions with no answers', () => {
    const qs = [boolQ('q1'), freeQ('q2')]
    expect(resolveActiveQuestions(qs, {})).toHaveLength(2)
  })

  it('preserves question order', () => {
    const qs = [freeQ('a'), freeQ('b'), freeQ('c')]
    const ids = resolveActiveQuestions(qs, {}).map(q => q.id)
    expect(ids).toEqual(['a', 'b', 'c'])
  })
})

describe('resolveActiveQuestions — BoolFollowUp', () => {
  const child = freeQ('detail')
  const parent = boolQ('has_allergy', [{ when_equals: true, questions: [child] }])

  it('does not include follow-up when unanswered', () => {
    expect(resolveActiveQuestions([parent], {})).toHaveLength(1)
  })

  it('does not include follow-up when answer is false', () => {
    const a = { has_allergy: ans({ type: 'boolean' as const, value: false }) }
    expect(resolveActiveQuestions([parent], a)).toHaveLength(1)
  })

  it('includes follow-up when answer matches', () => {
    const a = { has_allergy: ans({ type: 'boolean' as const, value: true }) }
    const active = resolveActiveQuestions([parent], a)
    expect(active).toHaveLength(2)
    expect(active[1].id).toBe('detail')
  })
})

describe('resolveActiveQuestions — SelectFollowUp (single_select)', () => {
  const child = freeQ('followup')
  const parent = singleQ('method', ['Email', 'Phone', 'Post'], [
    { when_option_selected: 'Email', questions: [child] },
  ])

  it('does not include follow-up when unanswered', () => {
    expect(resolveActiveQuestions([parent], {})).toHaveLength(1)
  })

  it('includes follow-up when correct option selected', () => {
    const a = { method: ans({ type: 'single_select' as const, value: 'Email' }) }
    expect(resolveActiveQuestions([parent], a)).toHaveLength(2)
  })

  it('does not include follow-up for a different option', () => {
    const a = { method: ans({ type: 'single_select' as const, value: 'Phone' }) }
    expect(resolveActiveQuestions([parent], a)).toHaveLength(1)
  })
})

describe('resolveActiveQuestions — SelectFollowUp (multi_select)', () => {
  const child = freeQ('detail')
  const parent = multiQ('symptoms', ['Fever', 'Headache', 'Nausea'], [
    { when_option_selected: 'Fever', questions: [child] },
  ])

  it('includes follow-up when option is among selected', () => {
    const a = { symptoms: ans({ type: 'multi_select' as const, value: ['Fever', 'Headache'] }) }
    expect(resolveActiveQuestions([parent], a)).toHaveLength(2)
  })

  it('does not include follow-up when option not selected', () => {
    const a = { symptoms: ans({ type: 'multi_select' as const, value: ['Headache'] }) }
    expect(resolveActiveQuestions([parent], a)).toHaveLength(1)
  })
})

describe('resolveActiveQuestions — ExprFollowUp', () => {
  it('handles eq expression against number', () => {
    const child = freeQ('child')
    const parent = numQ('age', [{
      condition: { op: 'ge', left: { op: 'var', question_id: 'age' }, right: { op: 'lit', value: 18 } },
      questions: [child],
    }])

    const under = { age: ans({ type: 'number' as const, value: 16 }) }
    const over = { age: ans({ type: 'number' as const, value: 21 }) }

    expect(resolveActiveQuestions([parent], under)).toHaveLength(1)
    expect(resolveActiveQuestions([parent], over)).toHaveLength(2)
  })

  it('handles eq expression against boolean', () => {
    const child = freeQ('child')
    const parent = boolQ('q', [{
      condition: { op: 'eq', left: { op: 'var', question_id: 'q' }, right: { op: 'lit', value: true } },
      questions: [child],
    }])

    const yes = { q: ans({ type: 'boolean' as const, value: true }) }
    const no = { q: ans({ type: 'boolean' as const, value: false }) }

    expect(resolveActiveQuestions([parent], yes)).toHaveLength(2)
    expect(resolveActiveQuestions([parent], no)).toHaveLength(1)
  })

  it('handles and expression', () => {
    const child = freeQ('child')
    const parent = numQ('score', [{
      condition: {
        op: 'and',
        operands: [
          { op: 'ge', left: { op: 'var', question_id: 'score' }, right: { op: 'lit', value: 3 } },
          { op: 'le', left: { op: 'var', question_id: 'score' }, right: { op: 'lit', value: 7 } },
        ],
      },
      questions: [child],
    }])

    const below = { score: ans({ type: 'number' as const, value: 2 }) }
    const within = { score: ans({ type: 'number' as const, value: 5 }) }
    const above = { score: ans({ type: 'number' as const, value: 9 }) }

    expect(resolveActiveQuestions([parent], below)).toHaveLength(1)
    expect(resolveActiveQuestions([parent], within)).toHaveLength(2)
    expect(resolveActiveQuestions([parent], above)).toHaveLength(1)
  })

  it('handles or expression', () => {
    const child = freeQ('child')
    const parent = numQ('val', [{
      condition: {
        op: 'or',
        operands: [
          { op: 'eq', left: { op: 'var', question_id: 'val' }, right: { op: 'lit', value: 1 } },
          { op: 'eq', left: { op: 'var', question_id: 'val' }, right: { op: 'lit', value: 5 } },
        ],
      },
      questions: [child],
    }])

    const one = { val: ans({ type: 'number' as const, value: 1 }) }
    const five = { val: ans({ type: 'number' as const, value: 5 }) }
    const three = { val: ans({ type: 'number' as const, value: 3 }) }

    expect(resolveActiveQuestions([parent], one)).toHaveLength(2)
    expect(resolveActiveQuestions([parent], five)).toHaveLength(2)
    expect(resolveActiveQuestions([parent], three)).toHaveLength(1)
  })

  it('handles not expression', () => {
    const child = freeQ('child')
    const parent = boolQ('q', [{
      condition: { op: 'not', operand: { op: 'var', question_id: 'q' } },
      questions: [child],
    }])

    // not(missing) === true → fires before question answered
    expect(resolveActiveQuestions([parent], {})).toHaveLength(2)
    const no = { q: ans({ type: 'boolean' as const, value: false }) }
    expect(resolveActiveQuestions([parent], no)).toHaveLength(2)
    const yes = { q: ans({ type: 'boolean' as const, value: true }) }
    expect(resolveActiveQuestions([parent], yes)).toHaveLength(1)
  })

  it('handles contains expression (multi-select)', () => {
    const child = freeQ('child')
    const parent = multiQ('topics', ['A', 'B', 'C'], [{
      condition: {
        op: 'contains',
        haystack: { op: 'var', question_id: 'topics' },
        needle: { op: 'lit', value: 'A' },
      },
      questions: [child],
    }])

    const withA = { topics: ans({ type: 'multi_select' as const, value: ['A', 'C'] }) }
    const withoutA = { topics: ans({ type: 'multi_select' as const, value: ['B', 'C'] }) }

    expect(resolveActiveQuestions([parent], withA)).toHaveLength(2)
    expect(resolveActiveQuestions([parent], withoutA)).toHaveLength(1)
  })

  it('handles missing var: comparisons return false (not-fires)', () => {
    const child = freeQ('child')
    const parent = numQ('n', [{
      condition: { op: 'eq', left: { op: 'var', question_id: 'n' }, right: { op: 'lit', value: 42 } },
      questions: [child],
    }])
    expect(resolveActiveQuestions([parent], {})).toHaveLength(1)
  })
})

describe('resolveActiveQuestions — nested follow-ups', () => {
  it('recursively activates grandchild follow-ups', () => {
    const grandchild = freeQ('grandchild')
    const child = boolQ('child_q', [{ when_equals: true, questions: [grandchild] }])
    const root = boolQ('root_q', [{ when_equals: true, questions: [child] }])

    const noAnswers = {}
    const rootYes = { root_q: ans({ type: 'boolean' as const, value: true }) }
    const bothYes = {
      root_q: ans({ type: 'boolean' as const, value: true }),
      child_q: ans({ type: 'boolean' as const, value: true }),
    }

    expect(resolveActiveQuestions([root], noAnswers)).toHaveLength(1)
    expect(resolveActiveQuestions([root], rootYes)).toHaveLength(2)
    expect(resolveActiveQuestions([root], bothYes)).toHaveLength(3)
  })

  it('collapses grandchildren when parent trigger unfires', () => {
    const grandchild = freeQ('grand')
    const child = boolQ('child', [{ when_equals: true, questions: [grandchild] }])
    const root = boolQ('root', [{ when_equals: true, questions: [child] }])

    const rootNo = { root: ans({ type: 'boolean' as const, value: false }) }
    expect(resolveActiveQuestions([root], rootNo)).toHaveLength(1)
  })
})

describe('resolveActiveQuestions — multiple follow-ups on one question', () => {
  it('activates all triggered follow-up groups simultaneously', () => {
    const a = freeQ('a')
    const b = freeQ('b')
    const parent = singleQ('q', ['X', 'Y', 'Z'], [
      { when_option_selected: 'X', questions: [a] },
      { when_option_selected: 'Y', questions: [b] },
    ])

    const x = { q: ans({ type: 'single_select' as const, value: 'X' }) }
    const y = { q: ans({ type: 'single_select' as const, value: 'Y' }) }

    expect(resolveActiveQuestions([parent], x)).toHaveLength(2)
    expect(resolveActiveQuestions([parent], x).map(q => q.id)).toContain('a')
    expect(resolveActiveQuestions([parent], y).map(q => q.id)).toContain('b')
    expect(resolveActiveQuestions([parent], y).map(q => q.id)).not.toContain('a')
  })
})

// ── getFollowUpChildren ───────────────────────────────────────────────────────

describe('getFollowUpChildren', () => {
  it('returns empty for questions with no follow_ups field', () => {
    expect(getFollowUpChildren(freeQ('q'), {})).toHaveLength(0)
  })

  it('returns children only for fired follow-ups', () => {
    const child = freeQ('child')
    const parent = boolQ('p', [
      { when_equals: true, questions: [child] },
      { when_equals: false, questions: [freeQ('other')] },
    ])
    const yes = { p: ans({ type: 'boolean' as const, value: true }) }
    const children = getFollowUpChildren(parent, yes)
    expect(children).toHaveLength(1)
    expect(children[0].id).toBe('child')
  })

  it('returns children from all simultaneously-fired follow-ups', () => {
    const c1 = freeQ('c1')
    const c2 = freeQ('c2')
    const parent = multiQ('q', ['A', 'B'], [
      { when_option_selected: 'A', questions: [c1] },
      { when_option_selected: 'B', questions: [c2] },
    ])
    const both = { q: ans({ type: 'multi_select' as const, value: ['A', 'B'] }) }
    expect(getFollowUpChildren(parent, both)).toHaveLength(2)
  })
})
