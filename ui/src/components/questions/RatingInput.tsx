interface Props {
  value: number | undefined
  onChange: (v: number) => void
  minVal: number
  maxVal: number
  minLabel?: string | null
  maxLabel?: string | null
  disabled?: boolean
}

export default function RatingInput({ value, onChange, minVal, maxVal, minLabel, maxLabel, disabled }: Props) {
  const options = Array.from({ length: maxVal - minVal + 1 }, (_, i) => i + minVal)

  return (
    <div className="space-y-2">
      <div className="flex gap-2 flex-wrap">
        {options.map(n => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            disabled={disabled}
            className={`w-10 h-10 rounded-xl border-2 text-sm font-semibold transition-all ${
              value === n
                ? 'border-amber-500 bg-amber-400 text-white shadow-sm shadow-amber-200'
                : 'border-slate-200 bg-white text-slate-600 hover:border-amber-300 hover:bg-amber-50'
            } disabled:opacity-50`}
          >
            {n}
          </button>
        ))}
      </div>
      {(minLabel || maxLabel) && (
        <div className="flex justify-between text-xs text-slate-400 max-w-xs">
          <span>{minLabel}</span>
          <span>{maxLabel}</span>
        </div>
      )}
    </div>
  )
}
