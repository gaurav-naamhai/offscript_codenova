export type GuidanceDocument = { id: string; title: string; category: string; description: string; fileName: string; createdAt: string }
export const guidanceCategories = ['Brand voice', 'Visual identity', 'Claims', 'Other'] as const
export const sampleGuidance = [
  { id: 'sample-voice', title: 'Sample brand voice guide', category: 'Brand voice', description: 'Illustrative guidance: communicate clearly and use a consistent tone.' },
  { id: 'sample-claims', title: 'Sample claims checklist', category: 'Claims', description: 'Illustrative guidance: check factual claims against supporting sources.' },
] as const
