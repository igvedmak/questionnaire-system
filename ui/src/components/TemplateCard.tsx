import type { Template, TemplateStats } from '../types'

const TYPE_LABELS: Record<string, string> = {
  boolean: 'yes / no',
  single_select: 'single choice',
  multi_select: 'multiple choice',
  free_text: 'free text',
  number: 'number',
  date: 'date',
  rating: 'rating',
  email: 'email',
}

const TYPE_COLORS: Record<string, string> = {
  boolean: 'bg-blue-100 text-blue-700',
  single_select: 'bg-indigo-100 text-indigo-700',
  multi_select: 'bg-violet-100 text-violet-700',
  date: 'bg-teal-100 text-teal-700',
  free_text: 'bg-slate-100 text-slate-600',
  number: 'bg-orange-100 text-orange-700',
  rating: 'bg-amber-100 text-amber-700',
  email: 'bg-cyan-100 text-cyan-700',
}

interface Props {
  template: Template
  stats?: TemplateStats | null
  onStart: () => void
  starting: boolean
}

export default function TemplateCard({ template, stats, onStart, starting }: Props) {
  const typeSet = [...new Set(template.questions.map(q => q.type))]

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow flex flex-col">
      <div className="p-5 flex-1">
        <div className="flex items-start justify-between gap-3 mb-2">
          <h3 className="font-semibold text-slate-900 text-base leading-snug">{template.title}</h3>
          <span className="shrink-0 text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
            v{template.version}
          </span>
        </div>

        {template.description && (
          <p className="text-sm text-slate-500 mb-3 line-clamp-2">{template.description}</p>
        )}

        <div className="flex flex-wrap gap-1.5 mb-4">
          {typeSet.map(t => (
            <span key={t} className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[t] ?? 'bg-gray-100 text-gray-600'}`}>
              {TYPE_LABELS[t] ?? t.replace('_', ' ')}
            </span>
          ))}
        </div>

        <div className="flex items-center gap-4 text-xs text-slate-500">
          <span>{template.questions.length} questions</span>
          {stats && (
            <>
              <span>·</span>
              <span>{stats.submitted} submitted</span>
              {stats.total > 0 && (
                <>
                  <span>·</span>
                  <span>{Math.round(stats.completion_rate * 100)}% complete</span>
                </>
              )}
            </>
          )}
        </div>
      </div>

      <div className="px-5 pb-5">
        <button
          onClick={onStart}
          disabled={starting}
          className="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {starting ? 'Starting…' : 'Start questionnaire'}
        </button>
      </div>
    </div>
  )
}
