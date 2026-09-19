import assert from 'node:assert/strict'
import test from 'node:test'

import { fitDrawerWidth } from '../src/paneLayout.ts'

test('opening the default drawer fits it inside the current desktop window', () => {
  assert.equal(fitDrawerWidth(760, 1200, 306), 706)
})

test('a user-adjusted drawer width is preserved while it still fits', () => {
  assert.equal(fitDrawerWidth(620, 1200, 306), 620)
})

test('drawer width is clamped after the desktop window becomes narrower', () => {
  assert.equal(fitDrawerWidth(700, 1100, 306), 606)
})

test('drawer never becomes narrower than its existing minimum', () => {
  assert.equal(fitDrawerWidth(400, 1200, 306), 520)
  assert.equal(fitDrawerWidth(760, 900, 306), 520)
})
