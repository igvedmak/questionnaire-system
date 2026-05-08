interface Props {
  value: string | undefined
  onChange: (v: string) => void
  disabled?: boolean
}

export default function DateInput({ value, onChange, disabled }: Props) {
  return (
    <input
      type="date"
      value={value ?? ''}
      onChange={e => e.target.value && onChange(e.target.value)}
      disabled={disabled}
      className="w-full max-w-xs px-4 py-2.5 rounded-xl border-2 border-slate-200 focus:border-teal-500 focus:outline-none text-slate-800 text-sm disabled:opacity-50 transition-colors"
    />
  )
}
