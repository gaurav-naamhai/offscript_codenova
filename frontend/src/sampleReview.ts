export type Finding = { id: 'brand' | 'claim'; category: 'Brand' | 'Claims'; title: string; assessment: string; excerpt: string; explanation: string; source: string; sourceUrl?: string; replacement?: string; start: number }
export const sampleText = 'Welcome to MailChimp.\n\nGet up to 20% off selected plans.\n\nBuild your next campaign with confidence.'
export const sampleFindings: Finding[] = [
  { id: 'brand', category: 'Brand', title: 'Brand terminology', assessment: 'Potential issue', excerpt: 'MailChimp', explanation: 'The sample uses a different capitalization from the illustrative guidance.', source: 'Official Mailchimp sample rule: the name is one word, with a capital M and lowercase c.', sourceUrl: 'https://styleguide.mailchimp.com/writing-about-mailchimp/', replacement: 'Mailchimp', start: sampleText.indexOf('MailChimp') },
  { id: 'claim', category: 'Claims', title: 'Offer evidence', assessment: 'Insufficient evidence', excerpt: 'Get up to 20% off selected plans.', explanation: 'This illustrative offer has no supporting source in the sample.', source: 'No source provided for this illustrative offer.', start: sampleText.indexOf('Get up to 20% off selected plans.') },
]
export const sampleCorrected = sampleText.slice(0, sampleFindings[0].start) + 'Mailchimp' + sampleText.slice(sampleFindings[0].start + sampleFindings[0].excerpt.length)
