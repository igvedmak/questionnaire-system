import type { AnswerValue, Question } from '../../types'
import { getFollowUpChildren } from '../../utils/followups'
import BooleanInput from './BooleanInput'
import SingleSelectInput from './SingleSelectInput'
import MultiSelectInput from './MultiSelectInput'
import DateInput from './DateInput'
import FreeTextInput from './FreeTextInput'
import NumberInput from './NumberInput'
import RatingInput from './RatingInput'
import EmailInput from './EmailInput'

const TYPE_META: Record<string, { label: string; color: string }> = {
  boolean: { label: 'Yes / No', color: 'bg-blue-100 text-blue-600' },
  single_select: { label: 'Single choice', color: 'bg-indigo-100 text-indigo-600' },
  multi_select: { label: 'Multiple choice', color: 'bg-violet-100 text-violet-600' },
  date: { label: 'Date', color: 'bg-teal-100 text-teal-600' },
  free_text: { label: 'Free text', color: 'bg-slate-100 text-slate-500' },
  number: { label: 'Number', color: 'bg-orange-100 text-orange-600' },
  rating: { label: 'Rating', color: 'bg-amber-100 text-amber-600' },
  email: { label: 'Email', color: 'bg-cyan-100 text-cyan-600' },
}

interface Props {
  question: Question
  answers: Record<string, AnswerValue>
  onAnswer: (questionId: string, answer: AnswerValue) => void
  disabled?: boolean
  depth?: number
}

export default function QuestionBlock({ question: q, answers, onAnswer, disabled, depth = 0 }: Props) {
  const current = answers[q.id]
  const meta = TYPE_META[q.type] ?? { label: q.type, color: 'bg-gray-100 text-gray-500' }
  const children = getFollowUpChildren(q, answers)

  function renderInput() {
    switch (q.type) {
      case 'boolean':
        return (
          <BooleanInput
            value={current?.type === 'boolean' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'boolean', value: v })}
            disabled={disabled}
          />
        )
      case 'single_select':
        return (
          <SingleSelectInput
            options={q.options}
            value={current?.type === 'single_select' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'single_select', value: v })}
            disabled={disabled}
          />
        )
      case 'multi_select':
        return (
          <MultiSelectInput
            options={q.options}
            value={current?.type === 'multi_select' ? current.value : []}
            onChange={v => onAnswer(q.id, { type: 'multi_select', value: v })}
            disabled={disabled}
          />
        )
      case 'date':
        return (
          <DateInput
            value={current?.type === 'date' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'date', value: v })}
            disabled={disabled}
          />
        )
      case 'free_text':
        return (
          <FreeTextInput
            value={current?.type === 'free_text' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'free_text', value: v })}
            disabled={disabled}
            pii={q.pii}
          />
        )
      case 'number':
        return (
          <NumberInput
            value={current?.type === 'number' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'number', value: v })}
            min={q.min}
            max={q.max}
            integer={q.integer}
            disabled={disabled}
          />
        )
      case 'rating':
        return (
          <RatingInput
            value={current?.type === 'rating' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'rating', value: v })}
            minVal={q.min_val}
            maxVal={q.max_val}
            minLabel={q.min_label}
            maxLabel={q.max_label}
            disabled={disabled}
          />
        )
      case 'email':
        return (
          <EmailInput
            value={current?.type === 'email' ? current.value : undefined}
            onChange={v => onAnswer(q.id, { type: 'email', value: v })}
            disabled={disabled}
          />
        )
    }
  }

  return (
    <div className={`${depth > 0 ? 'ml-4 pl-4 border-l-2 border-indigo-200' : ''}`}>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${meta.color}`}>
              {meta.label}
            </span>
            {!q.required && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-400">
                Optional
              </span>
            )}
            {q.pii && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-600">
                🔒 PII
              </span>
            )}
            {current !== undefined && (
              <span className="ml-auto text-xs text-emerald-600 font-medium flex items-center gap-1">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Saved
              </span>
            )}
          </div>
          <p className="text-slate-900 font-medium text-sm leading-snug">{q.prompt}</p>
          {q.hint && <p className="text-xs text-slate-400 italic">{q.hint}</p>}
        </div>

        {renderInput()}
      </div>

      {children.length > 0 && (
        <div className="mt-3 space-y-3">
          {children.map(child => (
            <QuestionBlock
              key={child.id}
              question={child}
              answers={answers}
              onAnswer={onAnswer}
              disabled={disabled}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}
