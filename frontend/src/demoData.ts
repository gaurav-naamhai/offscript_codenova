export const reviews = [
  { name: 'Summer campaign', format: 'Image', status: 'Needs review', icon: 'image', tone: 'lavender' },
  { name: 'Product brochure', format: 'PDF', status: 'Changes requested', icon: 'file', tone: 'amber' },
  { name: 'Welcome email', format: 'Text', status: 'Approved', icon: 'mail', tone: 'sage' },
] as const

export const summary = [
  { count: '06', label: 'Awaiting review', icon: 'layers', tone: 'purple' },
  { count: '03', label: 'Needs revision', icon: 'alert', tone: 'orange' },
  { count: '12', label: 'Approved', icon: 'check', tone: 'green' },
] as const

export const demoGuidance = ['Mailchimp style guide', 'Friendly and clear', 'No brand guidance'] as const
export const demoChannels = ['Marketing email', 'Social media', 'Website', 'Other'] as const
export const sampleInsights = { top_guidelines: [{ guideline: 'Sample brand voice guidance', count: 3 }, { guideline: 'Sample claims guidance', count: 2 }], state_counts: { potential_issue: 3, insufficient_evidence: 2 }, total_flags: 5 }
