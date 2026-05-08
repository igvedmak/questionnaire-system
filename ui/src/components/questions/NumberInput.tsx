interface Props {
  value: number | undefined
  onChange: (v: number) => void
  min?: number | null
  max?: number | null
  integer?: boolean
  disabled?: boolean
}

export default function NumberInput({ value, onChange, min, max, integer, disabled }: Props) {
  return (
    <div className="space-y-1">
      <input
        type="number"
        value={value ?? ''}
        step={integer ? 1 : 'any'}
        min={min ?? undefined}
        max={max ?? undefined}
        onChange={e => {
          const n = integer ? parseInt(e.target.value, 10) : parseFloat(e.target.value)
          if (!isNaN(n)) onChange(n)
        }}
        disabled={disabled}
        className="w-full max-w-xs px-4 py-2.5 rounded-xl border-2 border-slate-200 focus:border-orange-500 focus:outline-none text-slate-800 text-sm disabled:opacity-50 transition-colors"
      />
      {(min != null || max != null) && (
        <p className="text-xs text-slate-400">
          {min != null && max != null ? `Range: ${min} – ${max}` : min != null ? `Min: ${min}` : `Max: ${max}`}
          {integer ? ' (integers only)' : ''}
        </p>
      )}
    </div>
  )
}
