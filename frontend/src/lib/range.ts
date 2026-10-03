export interface Range {
  id: string
  label: string
  hours: number
  buckets: number
}

export const RANGES: Range[] = [
  { id: '1h', label: '1 h', hours: 1, buckets: 60 },
  { id: '6h', label: '6 h', hours: 6, buckets: 72 },
  { id: '24h', label: '24 h', hours: 24, buckets: 48 },
  { id: '7d', label: '7 j', hours: 168, buckets: 56 },
  { id: '30d', label: '30 j', hours: 720, buckets: 60 },
]

export const DEFAULT_RANGE = RANGES[2]

export function findRange(id: string | null): Range {
  return RANGES.find((r) => r.id === id) ?? DEFAULT_RANGE
}
