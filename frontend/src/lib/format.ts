const number = new Intl.NumberFormat('fr-FR')
const compact = new Intl.NumberFormat('fr-FR', { notation: 'compact', maximumFractionDigits: 1 })

export const formatInt = (value: number) => number.format(value)
export const formatCompact = (value: number) => compact.format(value)

export function formatPercent(value: number | null): string {
  return value === null ? '-' : `${value.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %`
}

export function formatMs(value: number | null): string {
  if (value === null) return '-'
  return value >= 1000 ? `${(value / 1000).toFixed(1).replace('.', ',')} s` : `${Math.round(value)} ms`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`
  const units = ['Ko', 'Mo', 'Go', 'To']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} ${units[unit]}`
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '-'
  const total = Math.round(seconds)
  if (total < 60) return `${total} s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} min ${String(total % 60).padStart(2, '0')} s`
  const hours = Math.floor(minutes / 60)
  return `${hours} h ${String(minutes % 60).padStart(2, '0')} min`
}

/** "il y a 12 s", "il y a 3 min"... */
export function formatAge(seconds: number): string {
  if (seconds < 5) return "à l'instant"
  if (seconds < 60) return `il y a ${Math.round(seconds)} s`
  if (seconds < 3600) return `il y a ${Math.round(seconds / 60)} min`
  if (seconds < 86400) return `il y a ${Math.round(seconds / 3600)} h`
  return `il y a ${Math.round(seconds / 86400)} j`
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** Axis label of a time slice: the time of day for a short period, the date for a longer one. */
export function formatTick(iso: string, spanSeconds: number): string {
  const date = new Date(iso)
  if (spanSeconds <= 36 * 3600) {
    return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
}

/** Length of the period covered by a timeseries, in seconds. */
export function spanOf(series: { since: string; until: string }): number {
  return (new Date(series.until).getTime() - new Date(series.since).getTime()) / 1000
}
