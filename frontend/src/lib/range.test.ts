import { describe, expect, it } from 'vitest'
import { DEFAULT_RANGE, findRange, RANGES } from './range'

describe('findRange', () => {
  it('finds a known range', () => {
    expect(findRange('7d').hours).toBe(168)
  })
  it('falls back to 24 h for an unknown or missing one', () => {
    expect(findRange('nope')).toBe(DEFAULT_RANGE)
    expect(findRange(null)).toBe(DEFAULT_RANGE)
    expect(DEFAULT_RANGE.hours).toBe(24)
  })
  it('has a unique id per range, in growing order', () => {
    expect(new Set(RANGES.map((r) => r.id)).size).toBe(RANGES.length)
    expect(RANGES.map((r) => r.hours)).toEqual([...RANGES.map((r) => r.hours)].sort((a, b) => a - b))
  })
})
