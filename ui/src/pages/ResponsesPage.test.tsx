import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MOCK_TEMPLATE, MOCK_SUBMITTED } from '../test/mocks'

const mockApi = vi.hoisted(() => ({
  listTemplates: vi.fn(),
  listQuestionnaires: vi.fn(),
}))
vi.mock('../api/client', () => ({ api: mockApi }))

import ResponsesPage from './ResponsesPage'

function setup() {
  return { user: userEvent.setup(), ...render(<MemoryRouter><ResponsesPage /></MemoryRouter>) }
}

beforeEach(() => {
  vi.resetAllMocks()
  mockApi.listTemplates.mockResolvedValue([MOCK_TEMPLATE])
  mockApi.listQuestionnaires.mockResolvedValue([MOCK_SUBMITTED])
})

// ── rendering ────────────────────────────────────────────────────────────────

describe('ResponsesPage — rendering', () => {
  it('shows page heading', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('Responses')).toBeInTheDocument())
  })

  it('shows questionnaire row with template title', async () => {
    setup()
    expect(await screen.findByRole('cell', { name: 'Test survey' })).toBeInTheDocument()
  })

  it('shows Submitted badge for submitted questionnaires', async () => {
    setup()
    expect(await screen.findByText('✓ Submitted')).toBeInTheDocument()
  })

  it('shows empty state when no questionnaires', async () => {
    mockApi.listQuestionnaires.mockResolvedValue([])
    setup()
    expect(await screen.findByText(/No responses yet/)).toBeInTheDocument()
  })

  it('shows error state on API failure', async () => {
    mockApi.listQuestionnaires.mockRejectedValue(new Error('DB error'))
    setup()
    expect(await screen.findByText('DB error')).toBeInTheDocument()
  })
})

// ── filtering ────────────────────────────────────────────────────────────────

describe('ResponsesPage — filtering', () => {
  it('re-fetches with template filter when selector changes', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Responses'))
    await user.selectOptions(screen.getByRole('combobox'), 'tpl_test')
    await waitFor(() => expect(mockApi.listQuestionnaires).toHaveBeenCalledWith(
      expect.objectContaining({ template: 'tpl_test' })
    ))
  })

  it('re-fetches with include_drafts when checkbox toggled', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Responses'))
    await user.click(screen.getByLabelText(/Include drafts/))
    await waitFor(() => expect(mockApi.listQuestionnaires).toHaveBeenCalledWith(
      expect.objectContaining({ include_drafts: true })
    ))
  })
})

// ── detail panel ────────────────────────────────────────────────────────────

describe('ResponsesPage — detail panel', () => {
  it('opens panel when a row is clicked', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Test survey'))
    const dataRow = screen.getAllByRole('row')[1]
    await user.click(dataRow)
    expect(await screen.findByText('Do you agree?')).toBeInTheDocument()
  })

  it('shows answer values in detail panel', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Test survey'))
    await user.click(screen.getAllByRole('row')[1])
    expect(await screen.findByText('Yes')).toBeInTheDocument()
    expect(screen.getByText('Blue')).toBeInTheDocument()
  })

  it('closes panel on close button click', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Test survey'))
    await user.click(screen.getAllByRole('row')[1])
    await screen.findByText('Do you agree?')
    // The X button inside the panel — find by its SVG path
    const closeBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('path[d*="M6 18L18 6"]')
    )!
    await user.click(closeBtn)
    await waitFor(() => expect(screen.queryByText('Do you agree?')).not.toBeInTheDocument())
  })
})
