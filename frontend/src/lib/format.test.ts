import { describe, expect, it } from 'vitest'
import {
  formatAge,
  formatBytes,
  formatDuration,
  formatMs,
  formatPercent,
  formatTick,
  spanOf,
} from './format'

describe('formatMs', () => {
  it('shows milliseconds, then seconds', () => {
    expect(formatMs(87.4)).toBe('87 ms')
    expect(formatMs(1500)).toBe('1,5 s')
  })
  it('has a placeholder for no value', () => {
    expect(formatMs(null)).toBe('-')
  })
})

describe('formatBytes', () => {
  it('uses French units', () => {
    expect(formatBytes(512)).toBe('512 o')
    expect(formatBytes(2048)).toMatch(/^2 Ko$/)
    expect(formatBytes(5 * 1024 * 1024)).toMatch(/^5 Mo$/)
  })
})

describe('formatDuration', () => {
  it('goes from seconds to hours', () => {
    expect(formatDuration(42)).toBe('42 s')
    expect(formatDuration(125)).toBe('2 min 05 s')
    expect(formatDuration(3 * 3600 + 7 * 60)).toBe('3 h 07 min')
    expect(formatDuration(null)).toBe('-')
  })
})

describe('formatAge', () => {
  it('is relative', () => {
    expect(formatAge(1)).toBe("à l'instant")
    expect(formatAge(30)).toBe('il y a 30 s')
    expect(formatAge(600)).toBe('il y a 10 min')
    expect(formatAge(7200)).toBe('il y a 2 h')
  })
})

describe('formatPercent', () => {
  it('keeps one decimal at most', () => {
    expect(formatPercent(92.66)).toMatch(/^92,7\s%$/)
    expect(formatPercent(null)).toBe('-')
  })
})

describe('axis labels', () => {
  const start = '2026-10-03T14:30:00Z'
  it('shows the time on a short period and the date on a long one', () => {
    expect(formatTick(start, 3600)).toMatch(/^\d{2}:\d{2}$/)
    expect(formatTick(start, 7 * 86400)).toMatch(/^\d{2}\/\d{2}$/)
  })
  it('measures the period of a series', () => {
    expect(spanOf({ since: '2026-10-03T00:00:00Z', until: '2026-10-03T06:00:00Z' })).toBe(6 * 3600)
  })
})
