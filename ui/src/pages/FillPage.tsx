import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AnswerValue, Question, Template } from '../types'
import { resolveActiveQuestions } from '../utils/followups'
import ProgressBar from '../components/ProgressBar'
import QuestionBlock from '../components/questions/QuestionBlock'

type Phase = 'loading' | 'active' | 'submitted' | 'error'

export default function FillPage() {
  const { questionnaireId } = useParams<{ questionnaireId: string }>()
  const navigate = useNavigate()

  const [phase, setPhase] = useState<Phase>('loading')
  const [template, setTemplate] = useState<Template | null>(null)
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})
  const [errMsg, setErrMsg] = useState('')
  const [saving, setSaving] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // used to prevent stale-closure issues in the save callback
  const answersRef = useRef(answers)
  answersRef.current = answers

  useEffect(() => {
    if (!questionnaireId) return
    Promise.all([
      api.getQuestionnaire(questionnaireId),
    ]).then(([qn]) => {
      return api.getTemplate(qn.template_id, qn.template_version).then(tpl => ({ qn, tpl }))
    }).then(({ qn, tpl }) => {
      setTemplate(tpl)
      setAnswers(qn.answers)
      setPhase(qn.submitted_at ? 'submitted' : 'active')
    }).catch(e => {
      setErrMsg(String((e as Error).message))
      setPhase('error')
    })
  }, [questionnaireId])

  const saveAnswer = useCallback(async (questionId: string, answer: AnswerValue) => {
    if (!questionnaireId) return
    setAnswers(prev => ({ ...prev, [questionId]: answer }))
    setSaving(prev => new Set(prev).add(questionId))
    try {
      await api.upsertAnswer(questionnaireId, questionId, answer)
    } catch {
      // silently ignore — the answer is kept in local state
    } finally {
      setSaving(prev => { const s = new Set(prev); s.delete(questionId); return s })
    }
  }, [questionnaireId])

  async function handleSubmit() {
    if (!questionnaireId) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await api.submitQuestionnaire(questionnaireId)
      setPhase('submitted')
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  if (phase === 'loading') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-4">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm text-slate-500">Loading questionnaire…</p>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-4">
        <p className="text-red-600 font-medium">{errMsg}</p>
        <button onClick={() => navigate('/')} className="text-indigo-600 text-sm hover:underline">← Back to templates</button>
      </div>
    )
  }

  if (phase === 'submitted') {
    const answeredCount = Object.keys(answers).length
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-5">
        <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
          <svg className="w-8 h-8 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <div>
          <h2 className="text-xl font-bold text-slate-900">Submitted!</h2>
          <p className="text-slate-500 mt-1 text-sm">{template?.title} · {answeredCount} answers recorded</p>
        </div>
        <div className="flex gap-3 justify-center">
          <button onClick={() => navigate('/')} className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors">
            Start another
          </button>
          <button onClick={() => navigate('/responses')} className="px-5 py-2 border border-slate-200 text-slate-600 text-sm rounded-lg hover:bg-slate-50">
            View responses
          </button>
        </div>
      </div>
    )
  }

  if (!template) return null

  const activeQuestions: Question[] = resolveActiveQuestions(template.questions, answers)
  const requiredActive = activeQuestions.filter(q => q.required)
  const answeredRequired = requiredActive.filter(q => answers[q.id] !== undefined)
  const allDone = answeredRequired.length === requiredActive.length && requiredActive.length > 0
  const totalAnswered = activeQuestions.filter(q => answers[q.id] !== undefined).length
  const isSaving = saving.size > 0

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/')} className="text-slate-400 hover:text-slate-600 transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <span className="text-xs text-slate-400">{template.title}</span>
          {isSaving && (
            <span className="ml-auto text-xs text-slate-400 flex items-center gap-1">
              <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Saving…
            </span>
          )}
        </div>
        <h1 className="text-xl font-bold text-slate-900">{template.title}</h1>
        {template.description && <p className="text-sm text-slate-500">{template.description}</p>}
        <ProgressBar answered={totalAnswered} total={activeQuestions.length} />
      </div>

      {/* Questions */}
      <div className="space-y-4">
        {template.questions.map(q => (
          <QuestionBlock
            key={q.id}
            question={q}
            answers={answers}
            onAnswer={saveAnswer}
            depth={0}
          />
        ))}
      </div>

      {/* Submit */}
      <div className="pt-2 space-y-2">
        {submitError && (
          <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{submitError}</p>
        )}
        <button
          onClick={handleSubmit}
          disabled={!allDone || submitting}
          className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors"
        >
          {submitting ? 'Submitting…' : !allDone ? `Answer ${requiredActive.length - answeredRequired.length} more required question${requiredActive.length - answeredRequired.length === 1 ? '' : 's'} to submit` : 'Submit questionnaire'}
        </button>
        {!allDone && (
          <p className="text-xs text-center text-slate-400">Optional questions don't block submission</p>
        )}
      </div>
    </div>
  )
}
