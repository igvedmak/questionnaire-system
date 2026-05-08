interface Props {
  options: string[]
  value: string | undefined
  onChange: (v: string) => void
  disabled?: boolean
}

export default function SingleSelectInput({ options, value, onChange, disabled }: Props) {
  return (
    <div className="flex flex-col gap-2">
      {options.map(opt => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          disabled={disabled}
          className={`text-left px-4 py-3 rounded-xl border-2 text-sm transition-all ${
            value === opt
              ? 'border-indigo-500 bg-indigo-50 text-indigo-800 font-medium shadow-sm'
              : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-300 hover:bg-indigo-50/50'
          } disabled:opacity-50`}
        >
          <span className={`inline-flex items-center justify-center w-4 h-4 rounded-full border mr-3 shrink-0 ${
            value === opt ? 'border-indigo-500 bg-indigo-500' : 'border-slate-300'
          }`}>
            {value === opt && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
          </span>
          {opt}
        </button>
      ))}
    </div>
  )
}
