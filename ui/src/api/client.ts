import type { AnswerValue, LlmConfig, Questionnaire, Template, TemplateStats } from '../types'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(String(err?.detail ?? res.statusText))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  // templates
  listTemplates: () => req<Template[]>('/templates'),
  getTemplate: (id: string, version?: number) =>
    req<Template>(`/templates/${id}${version ? `?version=${version}` : ''}`),
  getTemplateStats: (id: string) => req<TemplateStats>(`/templates/${id}/stats`),
  aiGenerate: (description: string, save = true) =>
    req<Template>(`/templates/ai-generate?save=${save}`, {
      method: 'POST',
      body: JSON.stringify({ description }),
    }),
  getLlmConfig: () => req<LlmConfig>('/llm/config'),

  // questionnaires
  createQuestionnaire: (templateId: string, respondentId?: string) =>
    req<Questionnaire>('/questionnaires', {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId, respondent_id: respondentId ?? null }),
    }),
  getQuestionnaire: (id: string) => req<Questionnaire>(`/questionnaires/${id}`),
  listQuestionnaires: (params?: { template?: string; include_drafts?: boolean; page?: number }) => {
    const q = new URLSearchParams()
    if (params?.template) q.set('template', params.template)
    if (params?.include_drafts) q.set('include_drafts', 'true')
    if (params?.page) q.set('page', String(params.page))
    return req<Questionnaire[]>(`/questionnaires?${q}`)
  },
  upsertAnswer: (qid: string, questionId: string, answer: AnswerValue) =>
    req<Questionnaire>(`/questionnaires/${qid}/answers/${questionId}`, {
      method: 'PUT',
      body: JSON.stringify({ answer }),
    }),
  submitQuestionnaire: (qid: string) =>
    req<Questionnaire>(`/questionnaires/${qid}/submit`, { method: 'POST' }),
}
