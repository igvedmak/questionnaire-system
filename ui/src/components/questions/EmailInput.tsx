interface Props {
  value: string | undefined
  onChange: (v: string) => void
  disabled?: boolean
}

export default function EmailInput({ value, onChange, disabled }: Props) {
  return (
    <input
      type="email"
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      disabled={disabled}
      placeholder="you@example.com"
      className="w-full max-w-sm px-4 py-2.5 rounded-xl border-2 border-slate-200 focus:border-cyan-500 focus:outline-none text-slate-800 text-sm disabled:opacity-50 transition-colors placeholder:text-slate-400"
    />
  )
}
