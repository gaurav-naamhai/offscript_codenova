export type Readiness =
  | 'not_checked'
  | 'review_in_progress'
  | 'review_incomplete'
  | 'changes_required'
  | 'ready_for_human_review'
  | 'approved_for_publication'
  | 'approved_with_override'

const labels: Record<Readiness, string> = {
  not_checked: 'Not yet checked',
  review_in_progress: 'Review in progress',
  review_incomplete: 'Review incomplete',
  changes_required: 'Changes or authorised review required',
  ready_for_human_review: 'Ready for human review',
  approved_for_publication: 'Approved for publication',
  approved_with_override: 'Approved with override',
}

export function readinessLabel(value: string | null | undefined, status: string, stage?: string | null): string {
  if (stage === 'failed' || stage === 'incomplete') return labels.review_incomplete
  if (status === 'ai_review') return labels.review_in_progress
  if (status === 'draft') return labels.not_checked
  if (value && Object.hasOwn(labels, value)) return labels[value as Readiness]
  return stage === 'completed' ? 'Review status unavailable — refresh for details' : labels.not_checked
}

export function readinessExplanation(value: string | null | undefined): string {
  switch (value) {
    case 'not_checked': return 'This version has not completed a check. Earlier results do not apply.'
    case 'review_in_progress': return 'The current version is being checked.'
    case 'review_incomplete': return 'A check failed or returned incomplete results. Review and retry it.'
    case 'changes_required': return 'Open findings need correction or an authorised decision.'
    case 'ready_for_human_review': return 'The completed check found no open blocking findings; human approval is still required.'
    case 'approved_for_publication': return 'The current checked version has completed human approval.'
    case 'approved_with_override': return 'Human approval included an override. Review remaining risks and the recorded justification.'
    default: return 'No safety conclusion is available from an empty findings list.'
  }
}
