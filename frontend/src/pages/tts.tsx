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
import { useTtsCalls } from '@/hooks/queries'
import { useRange } from '@/hooks/use-range'
import { formatBytes, formatDateTime, formatInt, formatMs } from '@/lib/format'

function StatusBadge({ code }: { code: number }) {
  if (code < 400) return <Badge variant="outline">{code}</Badge>
  return <Badge variant={code >= 500 || code === 429 ? 'destructive' : 'secondary'}>{code}</Badge>
}

export function TtsPage() {
  const [range] = useRange()
  const [result, setResult] = useState<string | undefined>()
  const { data, error } = useTtsCalls(range, result)
  if (error && !data) return <ErrorState error={error} />

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle>Requêtes de synthèse vocale</CardTitle>
        <FilterBar
          value={result}
          onChange={setResult}
          options={[
            { value: undefined, label: 'Toutes' },
            { value: 'ok', label: 'Réussies' },
            { value: 'client_error', label: 'Erreurs client' },
            { value: 'error', label: 'Erreurs serveur' },
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
                <TableHead>Date</TableHead>
                <TableHead>Code</TableHead>
                <TableHead>Worker</TableHead>
                <TableHead>Voix</TableHead>
                <TableHead>Format</TableHead>
                <TableHead className="text-right">Caractères</TableHead>
                <TableHead className="text-right">Audio</TableHead>
                <TableHead className="text-right">Premier octet</TableHead>
                <TableHead className="text-right">Durée</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-muted-foreground py-8 text-center">
                    Aucune requête sur la période.
                  </TableCell>
                </TableRow>
              )}
              {data.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="text-sm tabular-nums">{formatDateTime(c.at)}</TableCell>
                  <TableCell>
                    <StatusBadge code={c.status_code} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{c.instance ?? '-'}</TableCell>
                  <TableCell className="font-mono text-xs">{c.voice ?? '-'}</TableCell>
                  <TableCell className="uppercase">{c.format ?? '-'}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatInt(c.characters)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatBytes(c.audio_bytes)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatMs(c.first_byte_ms)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatMs(c.duration_ms)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
