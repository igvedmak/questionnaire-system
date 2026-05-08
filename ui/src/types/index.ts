// Mirrors backend domain/types.py and domain/expression.py exactly.

export type Expression =
  | { op: 'lit'; value: boolean | number | string | string[] }
  | { op: 'var'; question_id: string }
  | { op: 'eq' | 'ne' | 'gt' | 'lt' | 'ge' | 'le' | 'in'; left: Expression; right: Expression }
  | { op: 'contains'; haystack: Expression; needle: Expression }
  | { op: 'and' | 'or'; operands: Expression[] }
  | { op: 'not'; operand: Expression }

export interface BoolFollowUp { when_equals: boolean; questions: Question[] }
export interface SelectFollowUp { when_option_selected: string; questions: Question[] }
export interface ExprFollowUp { condition: Expression; questions: Question[] }
export type FollowUp = BoolFollowUp | SelectFollowUp | ExprFollowUp

interface BaseQuestion {
  id: string
  prompt: string
  pii: boolean
  required: boolean
  hint?: string | null
}

export interface BooleanQuestion extends BaseQuestion { type: 'boolean'; follow_ups: FollowUp[] }
export interface SingleSelectQuestion extends BaseQuestion { type: 'single_select'; options: string[]; follow_ups: FollowUp[] }
export interface MultiSelectQuestion extends BaseQuestion { type: 'multi_select'; options: string[]; follow_ups: FollowUp[] }
export interface DateQuestion extends BaseQuestion { type: 'date' }
export interface FreeTextQuestion extends BaseQuestion { type: 'free_text' }
export interface NumberQuestion extends BaseQuestion { type: 'number'; min: number | null; max: number | null; integer: boolean; follow_ups: FollowUp[] }
export interface RatingQuestion extends BaseQuestion { type: 'rating'; min_val: number; max_val: number; min_label?: string | null; max_label?: string | null }
export interface EmailQuestion extends BaseQuestion { type: 'email' }

export type Question =
  | BooleanQuestion | SingleSelectQuestion | MultiSelectQuestion
  | DateQuestion | FreeTextQuestion | NumberQuestion
  | RatingQuestion | EmailQuestion

export interface BooleanAnswer { type: 'boolean'; value: boolean }
export interface SingleSelectAnswer { type: 'single_select'; value: string }
export interface MultiSelectAnswer { type: 'multi_select'; value: string[] }
export interface DateAnswer { type: 'date'; value: string }
export interface FreeTextAnswer { type: 'free_text'; value: string }
export interface NumberAnswer { type: 'number'; value: number }
export interface RatingAnswer { type: 'rating'; value: number }
export interface EmailAnswer { type: 'email'; value: string }

export type AnswerValue =
  | BooleanAnswer | SingleSelectAnswer | MultiSelectAnswer
  | DateAnswer | FreeTextAnswer | NumberAnswer
  | RatingAnswer | EmailAnswer

export interface Template {
  id: string
  title: string
  description?: string | null
  questions: Question[]
  created_at: string
  version: number
  tags: string[]
}

export interface Questionnaire {
  id: string
  template_id: string
  template_version: number
  created_at: string
  submitted_at: string | null
  respondent_id: string | null
  answers: Record<string, AnswerValue>
  expires_at?: string | null
  archived_at?: string | null
}

export interface TemplateStats {
  template_id: string
  total: number
  submitted: number
  completion_rate: number
}
