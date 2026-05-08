import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AnswerValue, Questionnaire, Template } from '../types'

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function AnswerDisplay({ answer }: { answer: AnswerValue }) {
  switch (answer.type) {
    case 'boolean': return <span>{answer.value ? 'Yes' : 'No'}</span>
    case 'multi_select': return <span>{answer.value.join(', ')}</span>
    case 'rating': return <span>{'★'.repeat(answer.value)}{'☆'.repeat(5 - answer.value)}</span>
    default: return <span>{String(answer.value)}</span>
  }
}

interface DetailPanelProps {
  questionnaire: Questionnaire
  template: Template | undefined
  onClose: () => void
}

function DetailPanel({ questionnaire: qn, template, onClose }: DetailPanelProps) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-md bg-white shadow-2xl border-l border-slate-200 flex flex-col h-full">
        <div className="flex items-center justify-between p-4 border-b border-slate-200">
          <div>
            <h3 className="font-semibold text-slate-900 text-sm">{template?.title ?? qn.template_id}</h3>
            <p className="text-xs text-slate-400 mt-0.5">{qn.respondent_id ?? 'Anonymous'} · {formatDate(qn.submitted_at ?? qn.created_at)}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {Object.entries(qn.answers).length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">No answers recorded</p>
          ) : (
            Object.entries(qn.answers).map(([qid, ans]) => {
              const question = template?.questions.flatMap(q => [q]).find(q => q.id === qid)
              return (
                <div key={qid} className="bg-slate-50 rounded-lg p-3 space-y-1">
                  <p className="text-xs text-slate-500 font-medium">{question?.prompt ?? qid}</p>
                  <p className="text-sm text-slate-900 font-medium">
                    <AnswerDisplay answer={ans} />
                  </p>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}

export default function ResponsesPage() {
  const [questionnaires, setQuestionnaires] = useState<Questionnaire[]>([])
  const [templates, setTemplates] = useState<Record<string, Template>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterTemplate, setFilterTemplate] = useState<string>('')
  const [includeDrafts, setIncludeDrafts] = useState(false)
  const [selected, setSelected] = useState<Questionnaire | null>(null)

  useEffect(() => {
    api.listTemplates().then(tpls => {
      const m: Record<string, Template> = {}
      tpls.forEach(t => { m[t.id] = t })
      setTemplates(m)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    api.listQuestionnaires({
      template: filterTemplate || undefined,
      include_drafts: includeDrafts,
    }).then(qns => {
      setQuestionnaires(qns)
      setError(null)
    }).catch(e => setError((e as Error).message))
      .finally(() => setLoading(false))
  }, [filterTemplate, includeDrafts])

  const templateOptions = Object.values(templates)

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Responses</h1>
          <p className="text-sm text-slate-500 mt-0.5">{questionnaires.length} questionnaire{questionnaires.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
            <input type="checkbox" checked={includeDrafts} onChange={e => setIncludeDrafts(e.target.checked)} className="rounded accent-indigo-600" />
            Include drafts
          </label>
          <select
            value={filterTemplate}
            onChange={e => setFilterTemplate(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All templates</option>
            {templateOptions.map(t => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-14 bg-white rounded-xl border border-slate-200 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-16 text-red-600">{error}</div>
      ) : questionnaires.length === 0 ? (
        <div className="text-center py-16 space-y-2">
          <div className="text-4xl">📭</div>
          <p className="text-slate-600 font-medium">No responses yet</p>
          <p className="text-sm text-slate-400">Submit a questionnaire first.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Template', 'Respondent', 'Answers', 'Status', 'Date'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {questionnaires.map((qn, i) => {
                const tpl = templates[qn.template_id]
                const isSubmitted = !!qn.submitted_at
                return (
                  <tr
                    key={qn.id}
                    onClick={() => setSelected(qn)}
                    className={`border-b border-slate-100 last:border-0 cursor-pointer hover:bg-indigo-50/50 transition-colors ${i % 2 === 0 ? '' : 'bg-slate-50/50'}`}
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{tpl?.title ?? qn.template_id}</td>
                    <td className="px-4 py-3 text-slate-500">{qn.respondent_id ?? <span className="italic text-slate-400">anonymous</span>}</td>
                    <td className="px-4 py-3 text-slate-500">{Object.keys(qn.answers).length}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                        isSubmitted ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                      }`}>
                        {isSubmitted ? '✓ Submitted' : '⏳ Draft'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{formatDate(isSubmitted ? qn.submitted_at! : qn.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <DetailPanel
          questionnaire={selected}
          template={templates[selected.template_id]}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
