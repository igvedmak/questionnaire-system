import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MOCK_TEMPLATE, MOCK_QUESTIONNAIRE } from '../test/mocks'

// vi.hoisted ensures the object exists before the factory runs at hoist time.
const mockNavigate = vi.hoisted(() => vi.fn())
const mockApi = vi.hoisted(() => ({
  listTemplates: vi.fn(),
  getTemplateStats: vi.fn(),
  createQuestionnaire: vi.fn(),
  aiGenerate: vi.fn(),
  getLlmConfig: vi.fn(),
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})
vi.mock('../api/client', () => ({ api: mockApi }))

import HomePage from './HomePage'

function setup() {
  return { user: userEvent.setup(), ...render(<MemoryRouter><HomePage /></MemoryRouter>) }
}

beforeEach(() => {
  vi.resetAllMocks()
  mockApi.listTemplates.mockResolvedValue([MOCK_TEMPLATE])
  mockApi.getTemplateStats.mockResolvedValue({ template_id: 'tpl_test', total: 5, submitted: 3, completion_rate: 0.6 })
  mockApi.createQuestionnaire.mockResolvedValue(MOCK_QUESTIONNAIRE)
  mockApi.aiGenerate.mockResolvedValue(MOCK_TEMPLATE)
  mockApi.getLlmConfig.mockResolvedValue({ model: 'anthropic/claude-opus-4-7', provider: 'Anthropic', configured: true })
})

describe('HomePage — template list', () => {
  it('shows loading skeletons initially', () => {
    mockApi.listTemplates.mockReturnValue(new Promise(() => {}))
    const { container } = setup()
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(6)
  })

  it('renders template title and description after load', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('Test survey')).toBeInTheDocument())
    expect(screen.getByText('A survey for testing')).toBeInTheDocument()
  })

  it('renders question type badges', async () => {
    setup()
    await waitFor(() => screen.getByText('Test survey'))
    expect(screen.getByText('yes / no')).toBeInTheDocument()
    expect(screen.getByText('single choice')).toBeInTheDocument()
    expect(screen.getByText('rating')).toBeInTheDocument()
    expect(screen.getByText('email')).toBeInTheDocument()
  })

  it('shows submission stats from API', async () => {
    setup()
    await waitFor(() => screen.getByText(/3 submitted/))
    expect(screen.getByText(/60% complete/)).toBeInTheDocument()
  })

  it('shows empty state when no templates', async () => {
    mockApi.listTemplates.mockResolvedValue([])
    setup()
    await waitFor(() => expect(screen.getByText(/No templates yet/)).toBeInTheDocument())
  })

  it('shows error state when API fails', async () => {
    mockApi.listTemplates.mockRejectedValue(new Error('Connection refused'))
    setup()
    await waitFor(() => expect(screen.getByText('Connection refused')).toBeInTheDocument())
  })
})

describe('HomePage — start questionnaire', () => {
  it('calls createQuestionnaire and navigates on Start click', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('Start questionnaire'))
    await user.click(screen.getByText('Start questionnaire'))
    expect(mockApi.createQuestionnaire).toHaveBeenCalledWith('tpl_test')
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/fill/qn_1'))
  })

  it('shows Starting… while request in flight', async () => {
    mockApi.createQuestionnaire.mockReturnValue(new Promise(() => {}))
    const { user } = setup()
    await waitFor(() => screen.getByText('Start questionnaire'))
    await user.click(screen.getByText('Start questionnaire'))
    expect(screen.getByText('Starting…')).toBeInTheDocument()
  })
})

describe('HomePage — AI Generate modal', () => {
  it('opens modal when AI Generate clicked', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('AI Generate'))
    await user.click(screen.getByText('AI Generate'))
    expect(screen.getByText('AI Template Generator')).toBeInTheDocument()
  })

  it('closes modal on Cancel', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('AI Generate'))
    await user.click(screen.getByText('AI Generate'))
    await user.click(screen.getByText('Cancel'))
    expect(screen.queryByText('AI Template Generator')).not.toBeInTheDocument()
  })

  it('Generate button disabled when description is empty', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('AI Generate'))
    await user.click(screen.getByText('AI Generate'))
    expect(screen.getByText('Generate template')).toBeDisabled()
  })

  it('calls aiGenerate and shows success result', async () => {
    const { user } = setup()
    await waitFor(() => screen.getByText('AI Generate'))
    await user.click(screen.getByText('AI Generate'))
    fireEvent.change(screen.getByPlaceholderText(/Describe/i), { target: { value: 'Employee survey' } })
    await user.click(screen.getByText('Generate template'))
    await waitFor(() => expect(mockApi.aiGenerate).toHaveBeenCalledWith('Employee survey', true))
    expect(await screen.findByText(/Generated:/)).toBeInTheDocument()
  })

  it('shows error message when AI generation fails', async () => {
    mockApi.aiGenerate.mockRejectedValue(new Error('LLM key missing'))
    const { user } = setup()
    await waitFor(() => screen.getByText('AI Generate'))
    await user.click(screen.getByText('AI Generate'))
    fireEvent.change(screen.getByPlaceholderText(/Describe/i), { target: { value: 'some description' } })
    await user.click(screen.getByText('Generate template'))
    expect(await screen.findByText('LLM key missing')).toBeInTheDocument()
  })
})
