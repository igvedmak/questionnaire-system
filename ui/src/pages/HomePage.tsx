import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Template, TemplateStats } from '../types'
import TemplateCard from '../components/TemplateCard'

export default function HomePage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [stats, setStats] = useState<Record<string, TemplateStats>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState<string | null>(null)

  const [showAI, setShowAI] = useState(false)
  const [aiDesc, setAiDesc] = useState('')
  const [aiSave, setAiSave] = useState(true)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)
  const [aiResult, setAiResult] = useState<Template | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const navigate = useNavigate()

  useEffect(() => {
    api.listTemplates()
      .then(tpls => {
        setTemplates(tpls)
        Promise.all(tpls.map(t => api.getTemplateStats(t.id).catch(() => null))).then(results => {
          const m: Record<string, TemplateStats> = {}
          results.forEach((s, i) => { if (s) m[tpls[i].id] = s })
          setStats(m)
        })
      })
      .catch(e => setError(String(e.message)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (showAI) setTimeout(() => textareaRef.current?.focus(), 50)
  }, [showAI])

  async function handleStart(templateId: string) {
    setStarting(templateId)
    try {
      const qn = await api.createQuestionnaire(templateId)
      navigate(`/fill/${qn.id}`)
    } catch (e) {
      alert('Failed to start: ' + (e as Error).message)
      setStarting(null)
    }
  }

  async function handleAIGenerate() {
    if (!aiDesc.trim()) return
    setAiLoading(true)
    setAiError(null)
    setAiResult(null)
    try {
      const tpl = await api.aiGenerate(aiDesc.trim(), aiSave)
      setAiResult(tpl)
      if (aiSave) {
        setTemplates(prev => [tpl, ...prev.filter(t => t.id !== tpl.id)])
      }
    } catch (e) {
      setAiError((e as Error).message)
    } finally {
      setAiLoading(false)
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header row */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Templates</h1>
          <p className="text-sm text-slate-500 mt-0.5">Choose a template to start a new questionnaire</p>
        </div>
        <button
          onClick={() => { setShowAI(true); setAiResult(null); setAiError(null); setAiDesc('') }}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          AI Generate
        </button>
      </div>

      {/* AI Generate Modal */}
      {showAI && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm" onClick={e => e.target === e.currentTarget && setShowAI(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 space-y-5">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">AI Template Generator</h2>
                <p className="text-sm text-slate-500 mt-0.5">Describe what you want to survey and Claude will design the template.</p>
              </div>
              <button onClick={() => setShowAI(false)} className="text-slate-400 hover:text-slate-600">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <textarea
              ref={textareaRef}
              rows={4}
              value={aiDesc}
              onChange={e => setAiDesc(e.target.value)}
              placeholder="Describe your survey (e.g. Employee satisfaction covering workload, team culture, and career growth)"
              className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 focus:border-violet-500 focus:outline-none text-slate-800 text-sm resize-none placeholder:text-slate-400"
            />

            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
              <input type="checkbox" checked={aiSave} onChange={e => setAiSave(e.target.checked)} className="rounded accent-violet-600" />
              Save template after generation
            </label>

            {aiError && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{aiError}</p>}

            {aiResult && (
              <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 space-y-1">
                <p className="text-sm font-medium text-emerald-800">✓ Generated: <span className="font-semibold">{aiResult.title}</span></p>
                <p className="text-xs text-emerald-600">{aiResult.questions.length} questions · {aiSave ? 'Saved to library' : 'Preview only'}</p>
                {aiSave && (
                  <button
                    onClick={() => { setShowAI(false); handleStart(aiResult.id) }}
                    className="text-xs text-emerald-700 underline"
                  >
                    Start this questionnaire →
                  </button>
                )}
              </div>
            )}

            <div className="flex gap-3">
              <button
                onClick={handleAIGenerate}
                disabled={aiLoading || !aiDesc.trim()}
                className="flex-1 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white text-sm font-medium rounded-xl transition-colors"
              >
                {aiLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating…
                  </span>
                ) : 'Generate template'}
              </button>
              <button onClick={() => setShowAI(false)} className="px-4 py-2.5 border border-slate-200 text-slate-600 text-sm rounded-xl hover:bg-slate-50">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-slate-200 h-48 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-20 space-y-3">
          <p className="text-red-600 font-medium">{error}</p>
          <p className="text-sm text-slate-500">Make sure the API is running at <code className="bg-slate-100 px-1 py-0.5 rounded text-xs">{import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}</code></p>
        </div>
      ) : templates.length === 0 ? (
        <div className="text-center py-20 space-y-3">
          <div className="text-4xl">📋</div>
          <p className="text-slate-600 font-medium">No templates yet</p>
          <p className="text-sm text-slate-400">Run <code className="bg-slate-100 px-1 py-0.5 rounded text-xs">qst template seed</code> to add demos, or use AI Generate above.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {templates.map(tpl => (
            <TemplateCard
              key={tpl.id}
              template={tpl}
              stats={stats[tpl.id]}
              onStart={() => handleStart(tpl.id)}
              starting={starting === tpl.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
