import assert from 'node:assert/strict'
import test from 'node:test'

import { readinessLabel, reviewReadiness } from '../src/reviewReadiness.ts'

test('unchecked and running versions never inherit a completed label', () => {
  assert.equal(readinessLabel(reviewReadiness('ready_for_human_review', 'draft', null)), 'Not yet checked')
  assert.equal(readinessLabel(reviewReadiness('ready_for_human_review', 'ai_review', 'extracting')), 'Review in progress')
  assert.equal(readinessLabel(reviewReadiness('ready_for_human_review', 'draft', 'failed')), 'Review incomplete')
})

test('approved override and unavailable legacy values remain distinct', () => {
  assert.equal(readinessLabel(reviewReadiness('approved_with_override', 'approved', 'completed')), 'Approved with override')
  assert.equal(readinessLabel(reviewReadiness('ready', 'manager_review', 'completed')), 'Not yet checked')
})
