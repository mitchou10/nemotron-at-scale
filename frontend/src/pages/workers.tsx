import { ErrorState } from '@/components/error-state'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useWorkers } from '@/hooks/queries'
import { formatAge, formatMs } from '@/lib/format'
import { cn } from '@/lib/utils'

const KIND_LABEL = { nemo: 'STT · Nemo', vosk: 'STT · Vosk', tts: 'TTS · Piper' } as const

function Load({ active, max }: { active: number; max: number }) {
  const pct = max ? Math.min(100, (active / max) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="bg-muted h-1.5 w-20 overflow-hidden rounded-full">
        <div
          className={cn('h-full rounded-full', pct >= 100 ? 'bg-rose-500' : pct >= 80 ? 'bg-amber-500' : 'bg-emerald-500')}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums">
        {active} / {max}
      </span>
    </div>
  )
}

export function WorkersPage() {
  const { data, error } = useWorkers()
  if (error && !data) return <ErrorState error={error} />

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workers enregistrés</CardTitle>
      </CardHeader>
      <CardContent>
        {!data ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>État</TableHead>
                <TableHead>Identifiant</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Adresse</TableHead>
                <TableHead>Priorité</TableHead>
                <TableHead>Charge</TableHead>
                <TableHead>Latence</TableHead>
                <TableHead>Dernier signe de vie</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-muted-foreground py-8 text-center">
                    Aucun worker enregistré. Ils apparaissent dès leur premier heartbeat.
                  </TableCell>
                </TableRow>
              )}
              {data.map((w) => (
                <TableRow key={w.id}>
                  <TableCell>
                    <span className="flex items-center gap-2 text-sm">
                      <span className={cn('size-2 rounded-full', w.healthy ? 'bg-emerald-500' : 'bg-rose-500')} />
                      {w.healthy ? 'Opérationnel' : 'Injoignable'}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{w.id}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{KIND_LABEL[w.kind]}</Badge>
                  </TableCell>
                  <TableCell className="max-w-64 truncate font-mono text-xs" title={w.url}>
                    {w.url}
                  </TableCell>
                  <TableCell className="tabular-nums">{w.priority}</TableCell>
                  <TableCell>
                    <Load active={w.active} max={w.max_streams} />
                  </TableCell>
                  <TableCell className="tabular-nums">{formatMs(w.latency_ms)}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">{formatAge(w.age_s)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
