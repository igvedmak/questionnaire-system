import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import QuestionBlock from './QuestionBlock'
import type { AnswerValue, Question } from '../../types'

// ── helpers ──────────────────────────────────────────────────────────────────

function q(overrides: Partial<Question> & { type: Question['type'] }): Question {
  return { id: 'q1', prompt: 'Test question?', pii: false, required: true, ...overrides } as Question
}

function renderBlock(question: Question, answers: Record<string, AnswerValue> = {}, onAnswer = vi.fn()) {
  return { user: userEvent.setup(), onAnswer, ...render(
    <QuestionBlock question={question} answers={answers} onAnswer={onAnswer} />
  )}
}

// ── prompt / meta badges ─────────────────────────────────────────────────────

describe('QuestionBlock — prompt and badges', () => {
  it('shows prompt text', () => {
    renderBlock(q({ type: 'free_text', prompt: 'What is your name?' }))
    expect(screen.getByText('What is your name?')).toBeInTheDocument()
  })

  it('shows Optional badge for non-required', () => {
    renderBlock(q({ type: 'free_text', required: false }))
    expect(screen.getByText('Optional')).toBeInTheDocument()
  })

  it('shows PII badge when pii=true', () => {
    renderBlock(q({ type: 'free_text', pii: true }))
    // QuestionBlock renders "🔒 PII" span; use exact match to avoid matching
    // the FreeTextInput's "Encrypted at rest (PII field)" note
    expect(screen.getByText('🔒 PII')).toBeInTheDocument()
  })

  it('shows Saved badge when question is answered', () => {
    renderBlock(q({ type: 'free_text' }), { q1: { type: 'free_text', value: 'hello' } })
    expect(screen.getByText('Saved')).toBeInTheDocument()
  })

  it('does not show Saved badge when unanswered', () => {
    renderBlock(q({ type: 'free_text' }))
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('shows hint text when provided', () => {
    renderBlock(q({ type: 'free_text', hint: 'Enter your full legal name.' }))
    expect(screen.getByText('Enter your full legal name.')).toBeInTheDocument()
  })
})

// ── BooleanInput ─────────────────────────────────────────────────────────────

describe('BooleanInput', () => {
  // The type badge reads "Yes / No" — use role=button to avoid ambiguity.
  function yesBtn() { return screen.getByRole('button', { name: /✓ Yes/ }) }
  function noBtn() { return screen.getByRole('button', { name: /✗ No/ }) }

  it('renders Yes and No buttons', () => {
    renderBlock(q({ type: 'boolean', follow_ups: [] }))
    expect(yesBtn()).toBeInTheDocument()
    expect(noBtn()).toBeInTheDocument()
  })

  it('calls onAnswer with true when Yes clicked', async () => {
    const { user, onAnswer } = renderBlock(q({ type: 'boolean', follow_ups: [] }))
    await user.click(yesBtn())
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'boolean', value: true })
  })

  it('calls onAnswer with false when No clicked', async () => {
    const { user, onAnswer } = renderBlock(q({ type: 'boolean', follow_ups: [] }))
    await user.click(noBtn())
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'boolean', value: false })
  })
})

// ── SingleSelectInput ─────────────────────────────────────────────────────────

describe('SingleSelectInput', () => {
  const question = q({ type: 'single_select', options: ['Alpha', 'Beta', 'Gamma'], follow_ups: [] })

  it('renders all options', () => {
    renderBlock(question)
    ;['Alpha', 'Beta', 'Gamma'].forEach(o => expect(screen.getByText(o)).toBeInTheDocument())
  })

  it('calls onAnswer with selected value', async () => {
    const { user, onAnswer } = renderBlock(question)
    await user.click(screen.getByText('Beta'))
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'single_select', value: 'Beta' })
  })

  it('changes selection when another option clicked', async () => {
    const { user, onAnswer } = renderBlock(question)
    await user.click(screen.getByText('Alpha'))
    await user.click(screen.getByText('Gamma'))
    expect(onAnswer).toHaveBeenLastCalledWith('q1', { type: 'single_select', value: 'Gamma' })
  })
})

// ── MultiSelectInput ─────────────────────────────────────────────────────────

describe('MultiSelectInput', () => {
  const question = q({ type: 'multi_select', options: ['Fever', 'Headache', 'Nausea'], follow_ups: [] })

  it('renders all options', () => {
    renderBlock(question)
    ;['Fever', 'Headache', 'Nausea'].forEach(o => expect(screen.getByText(o)).toBeInTheDocument())
  })

  it('calls onAnswer with single selected value', async () => {
    const { user, onAnswer } = renderBlock(question)
    await user.click(screen.getByText('Fever'))
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'multi_select', value: ['Fever'] })
  })

  it('accumulates multiple selections', async () => {
    const { user, onAnswer } = renderBlock(
      question,
      { q1: { type: 'multi_select', value: ['Fever'] } }
    )
    await user.click(screen.getByText('Headache'))
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'multi_select', value: ['Fever', 'Headache'] })
  })

  it('removes option when clicked again (toggle)', async () => {
    const { user, onAnswer } = renderBlock(
      question,
      { q1: { type: 'multi_select', value: ['Fever', 'Headache'] } }
    )
    await user.click(screen.getByText('Fever'))
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'multi_select', value: ['Headache'] })
  })
})

// ── RatingInput ───────────────────────────────────────────────────────────────

describe('RatingInput', () => {
  const question = q({ type: 'rating', min_val: 1, max_val: 5 })

  it('renders buttons from min_val to max_val', () => {
    renderBlock(question)
    ;[1, 2, 3, 4, 5].forEach(n => expect(screen.getByRole('button', { name: String(n) })).toBeInTheDocument())
  })

  it('calls onAnswer with numeric value', async () => {
    const { user, onAnswer } = renderBlock(question)
    await user.click(screen.getByRole('button', { name: '4' }))
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'rating', value: 4 })
  })

  it('respects custom min_val / max_val', () => {
    renderBlock(q({ type: 'rating', min_val: 0, max_val: 10 }))
    ;[0, 5, 10].forEach(n => expect(screen.getByRole('button', { name: String(n) })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '11' })).not.toBeInTheDocument()
  })

  it('shows min_label and max_label when provided', () => {
    renderBlock(q({ type: 'rating', min_val: 1, max_val: 5, min_label: 'Terrible', max_label: 'Excellent' }))
    expect(screen.getByText('Terrible')).toBeInTheDocument()
    expect(screen.getByText('Excellent')).toBeInTheDocument()
  })
})

// ── NumberInput ───────────────────────────────────────────────────────────────

describe('NumberInput', () => {
  it('calls onAnswer on valid input', () => {
    const onAnswer = vi.fn()
    renderBlock(q({ type: 'number', min: null, max: null, integer: false, follow_ups: [] }), {}, onAnswer)
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '42.5' } })
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'number', value: 42.5 })
  })

  it('shows range hint when min and max set', () => {
    renderBlock(q({ type: 'number', min: 18, max: 120, integer: true, follow_ups: [] }))
    expect(screen.getByText(/Range: 18 – 120/)).toBeInTheDocument()
    expect(screen.getByText(/integers only/)).toBeInTheDocument()
  })
})

// ── EmailInput ────────────────────────────────────────────────────────────────

describe('EmailInput', () => {
  it('calls onAnswer on input change', () => {
    const onAnswer = vi.fn()
    renderBlock(q({ type: 'email' }), {}, onAnswer)
    // Use fireEvent.change (not userEvent.type) to set the full value at once
    // on a controlled input whose value prop doesn't update between keystrokes.
    fireEvent.change(screen.getByPlaceholderText(/you@example.com/), { target: { value: 'alice@example.com' } })
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'email', value: 'alice@example.com' })
  })
})

// ── DateInput ─────────────────────────────────────────────────────────────────

describe('DateInput', () => {
  it('calls onAnswer when a date is selected', () => {
    const onAnswer = vi.fn()
    renderBlock(q({ type: 'date' }), {}, onAnswer)
    fireEvent.change(screen.getByDisplayValue(''), { target: { value: '2024-06-15' } })
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'date', value: '2024-06-15' })
  })
})

// ── FreeTextInput ─────────────────────────────────────────────────────────────

describe('FreeTextInput', () => {
  it('calls onAnswer when text changes', () => {
    const onAnswer = vi.fn()
    renderBlock(q({ type: 'free_text' }), {}, onAnswer)
    fireEvent.change(screen.getByPlaceholderText(/Type your answer/), { target: { value: 'hello world' } })
    expect(onAnswer).toHaveBeenCalledWith('q1', { type: 'free_text', value: 'hello world' })
  })

  it('shows PII encryption notice when pii=true', () => {
    renderBlock(q({ type: 'free_text', pii: true }))
    expect(screen.getByText(/Encrypted at rest/)).toBeInTheDocument()
  })
})

// ── follow-up rendering ───────────────────────────────────────────────────────

describe('QuestionBlock — follow-up rendering', () => {
  const parent = q({
    type: 'boolean',
    follow_ups: [{ when_equals: true, questions: [
      { type: 'free_text', id: 'child_q', prompt: 'Which allergy?', pii: false, required: true },
    ]}],
  }) as Question

  it('renders follow-up child when trigger fires', () => {
    renderBlock(parent, { q1: { type: 'boolean', value: true } })
    expect(screen.getByText('Which allergy?')).toBeInTheDocument()
  })

  it('does not render follow-up when trigger does not fire', () => {
    renderBlock(parent, { q1: { type: 'boolean', value: false } })
    expect(screen.queryByText('Which allergy?')).not.toBeInTheDocument()
  })

  it('hides follow-up when unanswered', () => {
    renderBlock(parent, {})
    expect(screen.queryByText('Which allergy?')).not.toBeInTheDocument()
  })

  it('applies indentation style to nested questions', () => {
    const { container } = render(
      <QuestionBlock question={parent} answers={{ q1: { type: 'boolean', value: true } }} onAnswer={vi.fn()} />
    )
    expect(container.querySelector('.border-l-2')).toBeInTheDocument()
  })
})
