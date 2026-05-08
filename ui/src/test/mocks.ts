// Shared fixture data only — NO vi.mock() calls here.
// (Any vi.mock() inside a function is still hoisted and conflicts with
// the per-test-file mocks that each page test sets up.)

import type { Template, Questionnaire } from '../types'

export const MOCK_TEMPLATE: Template = {
  id: 'tpl_test',
  title: 'Test survey',
  description: 'A survey for testing',
  version: 1,
  created_at: '2024-01-01T00:00:00Z',
  tags: [],
  questions: [
    {
      type: 'boolean', id: 'q_bool', prompt: 'Do you agree?', pii: false, required: true,
      follow_ups: [
        { when_equals: true, questions: [
          { type: 'free_text', id: 'q_reason', prompt: 'Why do you agree?', pii: false, required: false },
        ]},
      ],
    },
    {
      type: 'single_select', id: 'q_color', prompt: 'Favourite colour?', pii: false, required: true,
      options: ['Red', 'Green', 'Blue'], follow_ups: [],
    },
    { type: 'rating', id: 'q_rating', prompt: 'Rate us', pii: false, required: true, min_val: 1, max_val: 5 },
    { type: 'email', id: 'q_email', prompt: 'Your email?', pii: false, required: false },
  ],
}

export const MOCK_QUESTIONNAIRE: Questionnaire = {
  id: 'qn_1',
  template_id: 'tpl_test',
  template_version: 1,
  created_at: '2024-06-01T10:00:00Z',
  submitted_at: null,
  respondent_id: null,
  answers: {},
}

export const MOCK_SUBMITTED: Questionnaire = {
  ...MOCK_QUESTIONNAIRE,
  submitted_at: '2024-06-01T10:05:00Z',
  answers: {
    q_bool: { type: 'boolean', value: true },
    q_color: { type: 'single_select', value: 'Blue' },
    q_rating: { type: 'rating', value: 4 },
  },
}
