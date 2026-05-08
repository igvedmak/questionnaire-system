import type {
  AnswerValue, BooleanAnswer, Expression, ExprFollowUp,
  BoolFollowUp, SelectFollowUp, FollowUp, MultiSelectAnswer,
  Question, SingleSelectAnswer,
} from '../types'

const MISSING = Symbol('MISSING')
type Val = boolean | number | string | string[] | typeof MISSING

function evalExpr(expr: Expression, answers: Record<string, AnswerValue>): Val {
  switch (expr.op) {
    case 'lit': return expr.value as Val
    case 'var': {
      const a = answers[expr.question_id]
      if (a === undefined) return MISSING
      return (a as AnswerValue & { value: Val }).value
    }
    case 'and': {
      for (const sub of expr.operands) {
        const v = evalExpr(sub, answers)
        if (v === MISSING || !v) return false
      }
      return true
    }
    case 'or': {
      for (const sub of expr.operands) {
        const v = evalExpr(sub, answers)
        if (v !== MISSING && v) return true
      }
      return false
    }
    case 'not': {
      const v = evalExpr(expr.operand, answers)
      return v === MISSING ? true : !v
    }
    case 'contains': {
      const h = evalExpr(expr.haystack, answers)
      const n = evalExpr(expr.needle, answers)
      if (h === MISSING || n === MISSING || !Array.isArray(h)) return false
      return h.includes(n as string)
    }
    case 'in': {
      const l = evalExpr(expr.left, answers)
      const r = evalExpr(expr.right, answers)
      if (l === MISSING || r === MISSING || !Array.isArray(r)) return false
      return r.includes(l as string)
    }
    default: {
      // binary comparisons
      const e = expr as { op: string; left: Expression; right: Expression }
      const l = evalExpr(e.left, answers)
      const r = evalExpr(e.right, answers)
      if (l === MISSING || r === MISSING) return false
      try {
        const ln = l as number, rn = r as number
        if (e.op === 'eq') return l === r
        if (e.op === 'ne') return l !== r
        if (e.op === 'gt') return ln > rn
        if (e.op === 'lt') return ln < rn
        if (e.op === 'ge') return ln >= rn
        if (e.op === 'le') return ln <= rn
      } catch { return false }
      return false
    }
  }
}

function followUpFires(q: Question, fu: FollowUp, answers: Record<string, AnswerValue>): boolean {
  if ('condition' in fu) {
    return evalExpr((fu as ExprFollowUp).condition, answers) === true
  }
  if ('when_equals' in fu) {
    if (q.type !== 'boolean') return false
    const a = answers[q.id] as BooleanAnswer | undefined
    return a !== undefined && a.value === (fu as BoolFollowUp).when_equals
  }
  if ('when_option_selected' in fu) {
    const target = (fu as SelectFollowUp).when_option_selected
    if (q.type === 'single_select') {
      const a = answers[q.id] as SingleSelectAnswer | undefined
      return a !== undefined && a.value === target
    }
    if (q.type === 'multi_select') {
      const a = answers[q.id] as MultiSelectAnswer | undefined
      return a !== undefined && a.value.includes(target)
    }
    return false
  }
  return false
}

export function resolveActiveQuestions(
  questions: Question[],
  answers: Record<string, AnswerValue>,
): Question[] {
  const out: Question[] = []
  for (const q of questions) {
    out.push(q)
    const followUps: FollowUp[] = ('follow_ups' in q ? q.follow_ups : []) as FollowUp[]
    for (const fu of followUps) {
      if (followUpFires(q, fu, answers)) {
        out.push(...resolveActiveQuestions(fu.questions, answers))
      }
    }
  }
  return out
}

export function getFollowUpChildren(
  q: Question,
  answers: Record<string, AnswerValue>,
): Question[] {
  const followUps: FollowUp[] = ('follow_ups' in q ? q.follow_ups : []) as FollowUp[]
  const out: Question[] = []
  for (const fu of followUps) {
    if (followUpFires(q, fu, answers)) {
      out.push(...fu.questions)
    }
  }
  return out
}
