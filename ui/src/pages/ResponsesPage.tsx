import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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

// ── Detail Panel ────────────────────────────────────────────────────────────

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

// ── Confirm Dialog ───────────────────────────────────────────────────────────

interface ConfirmDialogProps {
  title: string
  message: string
  confirmLabel: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

function ConfirmDialog({ title, message, confirmLabel, danger = false, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="text-sm text-slate-500">{message}</p>
        <div className="flex gap-3 justify-end">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors ${
              danger ? 'bg-red-600 hover:bg-red-700' : 'bg-indigo-600 hover:bg-indigo-700'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Row Actions Menu ─────────────────────────────────────────────────────────

interface RowActionsProps {
  questionnaire: Questionnaire
  onView: () => void
  onEdit: () => void
  onArchive: () => void
  onDelete: () => void
}

function RowActions({ questionnaire: qn, onView, onEdit, onArchive, onDelete }: RowActionsProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const isDraft = !qn.submitted_at

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  return (
    <div ref={ref} className="relative" onClick={e => e.stopPropagation()}>
      <button
        onClick={() => setOpen(o => !o)}
        className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
        title="Actions"
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-44 bg-white rounded-xl shadow-lg border border-slate-200 py-1 z-20">
          <button
            onClick={() => { setOpen(false); onView() }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            View details
          </button>

          {isDraft && (
            <button
              onClick={() => { setOpen(false); onEdit() }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Continue editing
            </button>
          )}

          <button
            onClick={() => { setOpen(false); onArchive() }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
            </svg>
            Archive
          </button>

          <div className="my-1 border-t border-slate-100" />

          <button
            onClick={() => { setOpen(false); onDelete() }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Delete
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function ResponsesPage() {
  const navigate = useNavigate()
  const [questionnaires, setQuestionnaires] = useState<Questionnaire[]>([])
  const [templates, setTemplates] = useState<Record<string, Template>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterTemplate, setFilterTemplate] = useState<string>('')
  const [includeDrafts, setIncludeDrafts] = useState(false)
  const [selected, setSelected] = useState<Questionnaire | null>(null)

  type Pending = { type: 'delete' | 'archive'; qn: Questionnaire }
  const [pending, setPending] = useState<Pending | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  function reload() {
    setLoading(true)
    api.listQuestionnaires({
      template: filterTemplate || undefined,
      include_drafts: includeDrafts,
    }).then(qns => {
      setQuestionnaires(qns)
      setError(null)
    }).catch(e => setError((e as Error).message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    api.listTemplates().then(tpls => {
      const m: Record<string, Template> = {}
      tpls.forEach(t => { m[t.id] = t })
      setTemplates(m)
    }).catch(() => {})
  }, [])

  useEffect(() => { reload() }, [filterTemplate, includeDrafts])

  async function handleConfirmAction() {
    if (!pending) return
    setActionError(null)
    try {
      if (pending.type === 'delete') {
        await api.deleteQuestionnaire(pending.qn.id)
      } else {
        await api.archiveQuestionnaire(pending.qn.id)
      }
      setPending(null)
      if (selected?.id === pending.qn.id) setSelected(null)
      reload()
    } catch (e) {
      setActionError((e as Error).message)
    }
  }

  const templateOptions = Object.values(templates)
  const csvHref = `${import.meta.env.VITE_API_URL ?? ''}/questionnaires.csv`

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Responses</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {questionnaires.length} questionnaire{questionnaires.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <a
            href={csvHref}
            download
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
            title="Download all as CSV"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Export CSV
          </a>
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

      {/* Error banner */}
      {actionError && (
        <div className="mb-4 flex items-center justify-between bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {actionError}
          <button onClick={() => setActionError(null)} className="text-red-400 hover:text-red-600 ml-4">✕</button>
        </div>
      )}

      {/* Table */}
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
                {['Template', 'Respondent', 'Answers', 'Status', 'Date', ''].map((h, i) => (
                  <th key={i} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{h}</th>
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
                    <td className="px-4 py-3">
                      <RowActions
                        questionnaire={qn}
                        onView={() => setSelected(qn)}
                        onEdit={() => navigate(`/fill/${qn.id}`)}
                        onArchive={() => setPending({ type: 'archive', qn })}
                        onDelete={() => setPending({ type: 'delete', qn })}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail slide-over */}
      {selected && (
        <DetailPanel
          questionnaire={selected}
          template={templates[selected.template_id]}
          onClose={() => setSelected(null)}
        />
      )}

      {/* Confirm dialog */}
      {pending && (
        <ConfirmDialog
          title={pending.type === 'delete' ? 'Delete questionnaire?' : 'Archive questionnaire?'}
          message={
            pending.type === 'delete'
              ? 'This will permanently delete the questionnaire and all its answers. This cannot be undone.'
              : 'Archived questionnaires are hidden from the default view. You can still find them with the filter.'
          }
          confirmLabel={pending.type === 'delete' ? 'Delete' : 'Archive'}
          danger={pending.type === 'delete'}
          onConfirm={handleConfirmAction}
          onCancel={() => { setPending(null); setActionError(null) }}
        />
      )}
    </div>
  )
}
