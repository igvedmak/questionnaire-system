interface Props {
  answered: number
  total: number
}

export default function ProgressBar({ answered, total }: Props) {
  const pct = total === 0 ? 0 : Math.round((answered / total) * 100)
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-500">
        <span>{answered} of {total} answered</span>
        <span>{pct}%</span>
      </div>
      <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-indigo-500 rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
