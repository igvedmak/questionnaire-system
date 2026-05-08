interface Props {
  value: boolean | undefined
  onChange: (v: boolean) => void
  disabled?: boolean
}

export default function BooleanInput({ value, onChange, disabled }: Props) {
  return (
    <div className="flex gap-3">
      {([true, false] as const).map(opt => (
        <button
          key={String(opt)}
          type="button"
          onClick={() => onChange(opt)}
          disabled={disabled}
          className={`flex-1 py-3 px-5 rounded-xl border-2 text-sm font-semibold transition-all ${
            value === opt
              ? 'border-blue-500 bg-blue-50 text-blue-700 shadow-sm'
              : 'border-slate-200 bg-white text-slate-600 hover:border-blue-300 hover:bg-blue-50/50'
          } disabled:opacity-50`}
        >
          {opt ? '✓ Yes' : '✗ No'}
        </button>
      ))}
    </div>
  )
}
