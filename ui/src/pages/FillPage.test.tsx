import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { MOCK_TEMPLATE, MOCK_QUESTIONNAIRE, MOCK_SUBMITTED } from '../test/mocks'

const mockNavigate = vi.hoisted(() => vi.fn())
const mockApi = vi.hoisted(() => ({
  getQuestionnaire: vi.fn(),
  getTemplate: vi.fn(),
  upsertAnswer: vi.fn(),
  submitQuestionnaire: vi.fn(),
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})
vi.mock('../api/client', () => ({ api: mockApi }))

import FillPage from './FillPage'

function setup() {
  return {
    user: userEvent.setup(),
    ...render(
      <MemoryRouter initialEntries={['/fill/qn_1']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/fill/:questionnaireId" element={<FillPage />} />
        </Routes>
      </MemoryRouter>
    ),
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  mockApi.getQuestionnaire.mockResolvedValue(MOCK_QUESTIONNAIRE)
  mockApi.getTemplate.mockResolvedValue(MOCK_TEMPLATE)
  mockApi.upsertAnswer.mockResolvedValue(MOCK_QUESTIONNAIRE)
  mockApi.submitQuestionnaire.mockResolvedValue(MOCK_SUBMITTED)
})

// ── loading / error ──────────────────────────────────────────────────────────

describe('FillPage — loading', () => {
  it('shows spinner while loading', () => {
    mockApi.getQuestionnaire.mockReturnValue(new Promise(() => {}))
    setup()
    expect(screen.getByText(/Loading questionnaire/)).toBeInTheDocument()
  })

  it('shows error state when API fails', async () => {
    mockApi.getQuestionnaire.mockRejectedValue(new Error('Not found'))
    setup()
    await waitFor(() => expect(screen.getByText('Not found')).toBeInTheDocument())
  })
})

// ── template rendering ───────────────────────────────────────────────────────

describe('FillPage — template rendering', () => {
  it('shows template title', async () => {
    setup()
    expect(await screen.findByRole('heading', { name: 'Test survey' })).toBeInTheDocument()
  })

  it('shows all top-level question prompts', async () => {
    setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    ;['Do you agree?', 'Favourite colour?', 'Rate us', 'Your email?']
      .forEach(p => expect(screen.getByText(p)).toBeInTheDocument())
  })

  it('shows template description', async () => {
    setup()
    await waitFor(() => screen.getByText('A survey for testing'))
  })
})

// ── progress bar ─────────────────────────────────────────────────────────────

describe('FillPage — progress bar', () => {
  it('starts at 0 answered', async () => {
    setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    expect(screen.getByText(/0 of/)).toBeInTheDocument()
  })

  it('increments after answering a question', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Do you agree?'))
    await user.click(screen.getByRole('button', { name: /✓ Yes/ }))
    await waitFor(() => expect(screen.getByText(/1 of/)).toBeInTheDocument())
  })
})

// ── auto-save ────────────────────────────────────────────────────────────────

describe('FillPage — auto-save', () => {
  it('calls upsertAnswer when boolean answered', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Do you agree?'))
    await user.click(screen.getByRole('button', { name: /✓ Yes/ }))
    await waitFor(() => expect(mockApi.upsertAnswer).toHaveBeenCalledWith(
      'qn_1', 'q_bool', { type: 'boolean', value: true }
    ))
  })

  it('calls upsertAnswer when single-select answered', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Favourite colour?'))
    await user.click(screen.getByText('Blue'))
    await waitFor(() => expect(mockApi.upsertAnswer).toHaveBeenCalledWith(
      'qn_1', 'q_color', { type: 'single_select', value: 'Blue' }
    ))
  })

  it('shows Saved badge after answer stored', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Do you agree?'))
    await user.click(screen.getByRole('button', { name: /✗ No/ }))
    await waitFor(() => expect(screen.getAllByText('Saved').length).toBeGreaterThan(0))
  })
})

// ── follow-up questions ──────────────────────────────────────────────────────

describe('FillPage — follow-up questions', () => {
  it('reveals follow-up when boolean trigger fires', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Do you agree?'))
    expect(screen.queryByText('Why do you agree?')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /✓ Yes/ }))
    expect(await screen.findByText('Why do you agree?')).toBeInTheDocument()
  })

  it('hides follow-up when trigger stops firing', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Do you agree?'))
    await user.click(screen.getByRole('button', { name: /✓ Yes/ }))
    await screen.findByText('Why do you agree?')
    await user.click(screen.getByRole('button', { name: /✗ No/ }))
    await waitFor(() => expect(screen.queryByText('Why do you agree?')).not.toBeInTheDocument())
  })
})

// ── submit ───────────────────────────────────────────────────────────────────

describe('FillPage — submit', () => {
  it('submit button disabled when required questions unanswered', async () => {
    setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    expect(screen.getByRole('button', { name: /Answer \d+ more/ })).toBeDisabled()
  })

  it('submit button enabled when all required active questions answered', async () => {
    const { user } = setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    await user.click(screen.getByRole('button', { name: /✓ Yes/ }))    // q_bool (reveals optional follow-up)
    await user.click(screen.getByText('Red'))                           // q_color
    await user.click(screen.getByRole('button', { name: '3' }))        // q_rating
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Submit questionnaire/ })).not.toBeDisabled()
    })
  })

  it('calls submitQuestionnaire on submit', async () => {
    const { user } = setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    await user.click(screen.getByRole('button', { name: /✗ No/ }))
    await user.click(screen.getByText('Red'))
    await user.click(screen.getByRole('button', { name: '2' }))
    const btn = await screen.findByRole('button', { name: /Submit questionnaire/ })
    await user.click(btn)
    await waitFor(() => expect(mockApi.submitQuestionnaire).toHaveBeenCalledWith('qn_1'))
  })

  it('shows success screen after submit', async () => {
    const { user } = setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    await user.click(screen.getByRole('button', { name: /✗ No/ }))
    await user.click(screen.getByText('Green'))
    await user.click(screen.getByRole('button', { name: '5' }))
    const btn = await screen.findByRole('button', { name: /Submit questionnaire/ })
    await user.click(btn)
    expect(await screen.findByText('Submitted!')).toBeInTheDocument()
  })

  it('shows submit error on failure', async () => {
    mockApi.submitQuestionnaire.mockRejectedValue(new Error('Validation failed'))
    const { user } = setup()
    await screen.findByRole('heading', { name: 'Test survey' })
    await user.click(screen.getByRole('button', { name: /✗ No/ }))
    await user.click(screen.getByText('Blue'))
    await user.click(screen.getByRole('button', { name: '1' }))
    const btn = await screen.findByRole('button', { name: /Submit questionnaire/ })
    await user.click(btn)
    expect(await screen.findByText('Validation failed')).toBeInTheDocument()
  })
})

// ── already submitted ────────────────────────────────────────────────────────

describe('FillPage — already submitted questionnaire', () => {
  it('shows success screen immediately if already submitted', async () => {
    mockApi.getQuestionnaire.mockResolvedValue(MOCK_SUBMITTED)
    setup()
    expect(await screen.findByText('Submitted!')).toBeInTheDocument()
  })
})
