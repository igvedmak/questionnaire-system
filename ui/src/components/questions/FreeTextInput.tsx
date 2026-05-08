interface Props {
  value: string | undefined
  onChange: (v: string) => void
  disabled?: boolean
  pii?: boolean
}

export default function FreeTextInput({ value, onChange, disabled, pii }: Props) {
  return (
    <div className="space-y-1">
      <textarea
        rows={3}
        value={value ?? ''}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        placeholder="Type your answer…"
        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 focus:border-slate-500 focus:outline-none text-slate-800 text-sm resize-y disabled:opacity-50 transition-colors placeholder:text-slate-400"
      />
      {pii && (
        <p className="text-xs text-amber-600 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          Encrypted at rest (PII field)
        </p>
      )}
    </div>
  )
}
