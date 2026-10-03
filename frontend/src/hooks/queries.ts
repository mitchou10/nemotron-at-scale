import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { adminGet } from '@/lib/api'
import type { Range } from '@/lib/range'
import type { Overview, SttStream, Timeseries, TtsCall, Worker } from '@/lib/types'

const REFRESH_MS = 10_000

const live = { refetchInterval: REFRESH_MS, placeholderData: keepPreviousData }

export const useOverview = (range: Range) =>
  useQuery({
    queryKey: ['overview', range.id],
    queryFn: () => adminGet<Overview>('overview', { hours: range.hours }),
    ...live,
  })

export const useTimeseries = (range: Range) =>
  useQuery({
    queryKey: ['timeseries', range.id],
    queryFn: () => adminGet<Timeseries>('timeseries', { hours: range.hours, buckets: range.buckets }),
    ...live,
  })

export const useWorkers = () =>
  useQuery({ queryKey: ['workers'], queryFn: () => adminGet<Worker[]>('workers'), ...live })

export const useSttStreams = (range: Range, state: string | undefined) =>
  useQuery({
    queryKey: ['stt-streams', range.id, state],
    queryFn: () => adminGet<SttStream[]>('stt/streams', { hours: range.hours, limit: 200, state }),
    ...live,
  })

export const useTtsCalls = (range: Range, result: string | undefined) =>
  useQuery({
    queryKey: ['tts-calls', range.id, result],
    queryFn: () => adminGet<TtsCall[]>('tts/calls', { hours: range.hours, limit: 200, result }),
    ...live,
  })
