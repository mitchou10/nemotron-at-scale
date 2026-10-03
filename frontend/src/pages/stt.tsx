import { useState } from 'react'
import { ErrorState } from '@/components/error-state'
import { FilterBar } from '@/components/filter-bar'
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
import { useSttStreams } from '@/hooks/queries'
import { useRange } from '@/hooks/use-range'
import { formatDateTime, formatDuration } from '@/lib/format'
import type { SttStream } from '@/lib/types'

const STATUS: Record<SttStream['status'], { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  running: { label: 'En cours', variant: 'default' },
  recovering: { label: 'Reprise', variant: 'secondary' },
  ended: { label: 'Terminé', variant: 'outline' },
  failed: { label: 'Échec', variant: 'destructive' },
  interrupted: { label: 'Interrompu', variant: 'secondary' },
}

export function SttPage() {
  const [range] = useRange()
  const [state, setState] = useState<string | undefined>()
  const { data, error } = useSttStreams(range, state)
  if (error && !data) return <ErrorState error={error} />

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle>Flux de transcription</CardTitle>
        <FilterBar
          value={state}
          onChange={setState}
          options={[
            { value: undefined, label: 'Tous' },
            { value: 'active', label: 'En cours' },
            { value: 'ended', label: 'Terminés' },
            { value: 'failed', label: 'Échecs' },
            { value: 'interrupted', label: 'Interrompus' },
          ]}
        />
      </CardHeader>
      <CardContent>
        {!data ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Début</TableHead>
                <TableHead>Client</TableHead>
                <TableHead>Worker</TableHead>
                <TableHead>État</TableHead>
                <TableHead>Reprises</TableHead>
                <TableHead>Durée</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground py-8 text-center">
                    Aucun flux sur la période.
                  </TableCell>
                </TableRow>
              )}
              {data.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="text-sm tabular-nums">{formatDateTime(s.started_at)}</TableCell>
                  <TableCell className="font-mono text-xs">{s.client_id}</TableCell>
                  <TableCell className="font-mono text-xs">{s.instance}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS[s.status].variant}>{STATUS[s.status].label}</Badge>
                  </TableCell>
                  <TableCell className="tabular-nums">{s.failovers}</TableCell>
                  <TableCell className="tabular-nums">{formatDuration(s.duration_s)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
