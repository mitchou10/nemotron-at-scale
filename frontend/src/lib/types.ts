// Shapes of the backend admin API (backend/app/api/routes/admin.py).

export interface NamedCount {
  count: number
  instance?: string
  voice?: string
  format?: string
}

export interface SttSummary {
  streams: number
  active: number
  ended: number
  failed: number
  interrupted: number
  failovers: number
  unique_clients: number
  total_duration_s: number
  avg_duration_s: number | null
  by_instance: NamedCount[]
}

export interface TtsSummary {
  requests: number
  ok: number
  client_errors: number
  rate_limited: number
  server_errors: number
  success_rate_pct: number | null
  characters: number
  audio_bytes: number
  avg_duration_ms: number | null
  p50_duration_ms: number | null
  p95_duration_ms: number | null
  avg_first_byte_ms: number | null
  p95_first_byte_ms: number | null
  by_voice: NamedCount[]
  by_format: NamedCount[]
  by_instance: NamedCount[]
}

export interface Overview {
  since: string
  until: string
  hours: number
  stt: SttSummary
  tts: TtsSummary
  workers: {
    total: number
    healthy: number
    by_kind: Record<string, { total: number; healthy: number }>
    asr_enabled: boolean
  }
}

export interface TimeBucket {
  start: string
  stt_streams: number
  stt_failed: number
  tts_ok: number
  tts_failed: number
  tts_characters: number
  tts_avg_duration_ms: number | null
}

export interface Timeseries {
  since: string
  until: string
  bucket_seconds: number
  buckets: TimeBucket[]
}

export interface Worker {
  id: string
  kind: 'nemo' | 'vosk' | 'tts'
  url: string
  priority: number
  max_streams: number
  registered_at: string
  last_seen: string
  age_s: number
  healthy: boolean
  latency_ms: number | null
  active: number
}

export interface SttStream {
  id: string
  client_id: string
  instance: string
  status: 'running' | 'recovering' | 'ended' | 'failed' | 'interrupted'
  failovers: number
  started_at: string
  duration_s: number
}

export interface TtsCall {
  id: number
  at: string
  status_code: number
  instance: string | null
  voice: string | null
  format: string | null
  characters: number
  audio_bytes: number
  duration_ms: number
  first_byte_ms: number | null
}
