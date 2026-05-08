interface Props {
  options: string[]
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}

export default function MultiSelectInput({ options, value, onChange, disabled }: Props) {
  const toggle = (opt: string) => {
    onChange(value.includes(opt) ? value.filter(v => v !== opt) : [...value, opt])
  }

  return (
    <div className="flex flex-col gap-2">
      {options.map(opt => {
        const selected = value.includes(opt)
        return (
          <button
            key={opt}
            type="button"
            onClick={() => toggle(opt)}
            disabled={disabled}
            className={`text-left px-4 py-3 rounded-xl border-2 text-sm transition-all ${
              selected
                ? 'border-violet-500 bg-violet-50 text-violet-800 font-medium shadow-sm'
                : 'border-slate-200 bg-white text-slate-700 hover:border-violet-300 hover:bg-violet-50/50'
            } disabled:opacity-50`}
          >
            <span className={`inline-flex items-center justify-center w-4 h-4 rounded border mr-3 shrink-0 transition-colors ${
              selected ? 'border-violet-500 bg-violet-500' : 'border-slate-300'
            }`}>
              {selected && (
                <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              )}
            </span>
            {opt}
          </button>
        )
      })}
    </div>
  )
}
