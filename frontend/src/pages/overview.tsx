import {
  AudioLines,
  CircleCheck,
  Clock,
  Mic,
  RefreshCw,
  Server,
  Timer,
  TriangleAlert,
  Type,
  Users,
} from 'lucide-react'
import { BarList } from '@/components/bar-list'
import { CallsChart } from '@/components/calls-chart'
import { ErrorState } from '@/components/error-state'
import { LatencyChart } from '@/components/latency-chart'
import { StatCard } from '@/components/stat-card'
import { useRange } from '@/hooks/use-range'
import { useOverview, useTimeseries } from '@/hooks/queries'
import { formatCompact, formatDuration, formatInt, formatMs, formatPercent } from '@/lib/format'
import type { NamedCount, Overview } from '@/lib/types'
import { cn } from '@/lib/utils'

function named(items: NamedCount[] | undefined, key: 'instance' | 'voice' | 'format') {
  return (items ?? []).map((i) => ({ name: i[key] ?? '-', count: i.count }))
}

function WorkersBanner({ workers }: { workers: Overview['workers'] }) {
  const { total, healthy } = workers
  let tone = 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
  let text = `Tous les workers sont opérationnels (${healthy} / ${total})`
  if (total === 0) {
    tone = 'bg-muted text-muted-foreground'
    text = 'Aucun worker enregistré'
  } else if (healthy === 0) {
    tone = 'bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/30'
    text = `Panne : aucun worker disponible (0 / ${total})`
  } else if (healthy < total) {
    tone = 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30'
    text = `Service dégradé : ${total - healthy} worker(s) hors service sur ${total}`
  }
  const kinds = Object.entries(workers.by_kind)
  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-4 py-3 text-sm', tone)}>
      <span className="font-medium">{text}</span>
      {kinds.map(([kind, counts]) => (
        <span key={kind} className="opacity-80">
          {kind} {counts.healthy}/{counts.total}
        </span>
      ))}
    </div>
  )
}

export function OverviewPage() {
  const [range] = useRange()
  const overview = useOverview(range)
  const series = useTimeseries(range)
  const data = overview.data
  const tts = data?.tts
  const stt = data?.stt

  if (overview.error && !data) return <ErrorState error={overview.error} />

  const failures = tts ? tts.client_errors + tts.rate_limited + tts.server_errors : 0
  const successTone = tts?.success_rate_pct == null ? 'default' : tts.success_rate_pct >= 99 ? 'good' : tts.success_rate_pct >= 90 ? 'warn' : 'bad'

  return (
    <>
      {data && <WorkersBanner workers={data.workers} />}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Requêtes TTS"
          value={tts && formatInt(tts.requests)}
          hint={tts && `${formatInt(failures)} en échec`}
          icon={AudioLines}
        />
        <StatCard
          label="Taux de réussite TTS"
          value={tts && formatPercent(tts.success_rate_pct)}
          hint={tts && `${formatInt(tts.rate_limited)} refusées (429)`}
          icon={CircleCheck}
          tone={successTone}
        />
        <StatCard
          label="Durée p95 d'une synthèse"
          value={tts && formatMs(tts.p95_duration_ms)}
          hint={tts && `premier octet p95 : ${formatMs(tts.p95_first_byte_ms)}`}
          icon={Timer}
        />
        <StatCard
          label="Caractères synthétisés"
          value={tts && formatCompact(tts.characters)}
          hint={tts && `moyenne ${formatMs(tts.avg_duration_ms)} par requête`}
          icon={Type}
        />
        <StatCard
          label="Flux STT"
          value={stt && formatInt(stt.streams)}
          hint={stt && `${formatInt(stt.unique_clients)} clients distincts`}
          icon={Mic}
        />
        <StatCard
          label="Flux en cours"
          value={stt && formatInt(stt.active)}
          hint={data && (data.workers.asr_enabled ? 'transcription active' : 'transcription désactivée')}
          icon={Clock}
          tone={stt && stt.active > 0 ? 'good' : 'default'}
        />
        <StatCard
          label="Reprises / échecs STT"
          value={stt && `${formatInt(stt.failovers)} / ${formatInt(stt.failed)}`}
          hint={stt && `${formatInt(stt.interrupted)} interrompus`}
          icon={RefreshCw}
          tone={stt && stt.failed > 0 ? 'warn' : 'default'}
        />
        <StatCard
          label="Temps d'audio transcrit"
          value={stt && formatDuration(stt.total_duration_s)}
          hint={stt && `moyenne ${formatDuration(stt.avg_duration_s)} par flux`}
          icon={Users}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <CallsChart data={series.data} />
        <LatencyChart data={series.data} />
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <BarList title="Voix les plus utilisées" items={named(tts?.by_voice, 'voice')} />
        <BarList title="Formats audio demandés" items={named(tts?.by_format, 'format')} />
        <BarList title="Requêtes TTS par worker" items={named(tts?.by_instance, 'instance')} />
        <BarList title="Flux STT par worker" items={named(stt?.by_instance, 'instance')} />
      </section>

      {data && (
        <p className="text-muted-foreground flex items-center gap-1 text-xs">
          <Server className="size-3" /> {data.workers.total} worker(s) enregistré(s)
          {failures > 0 && (
            <>
              <TriangleAlert className="ml-3 size-3" /> {formatInt(failures)} requête(s) TTS en erreur sur la
              période
            </>
          )}
        </p>
      )}
    </>
  )
}
