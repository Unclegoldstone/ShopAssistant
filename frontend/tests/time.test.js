import test from 'node:test'
import assert from 'node:assert/strict'

import { formatConversationTime } from '../src/time.js'

test('formats a timezone-less database timestamp as Beijing time', () => {
  assert.equal(formatConversationTime('2026-09-30T04:42:59'), '09/30 12:42')
})

test('keeps an explicitly UTC timestamp on the same Beijing-time instant', () => {
  assert.equal(formatConversationTime('2026-09-30T04:42:59Z'), '09/30 12:42')
})

test('returns a placeholder for an invalid timestamp', () => {
  assert.equal(formatConversationTime('not-a-date'), '--')
})
