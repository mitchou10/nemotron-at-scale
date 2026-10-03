import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { formatTick, spanOf } from '@/lib/format'
import type { Timeseries } from '@/lib/types'

const config = {
  tts_ok: { label: 'TTS réussis', color: 'var(--chart-1)' },
  tts_failed: { label: 'TTS en échec', color: 'var(--chart-3)' },
  stt_streams: { label: 'Flux STT', color: 'var(--chart-2)' },
} satisfies ChartConfig

export function CallsChart({ data }: { data: Timeseries | undefined }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appels dans le temps</CardTitle>
        <CardDescription>Requêtes de synthèse vocale et flux de transcription démarrés.</CardDescription>
      </CardHeader>
      <CardContent>
        {!data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <ChartContainer config={config} className="h-64 w-full">
            <BarChart data={data.buckets} margin={{ left: 0, right: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="start"
                tickLine={false}
                axisLine={false}
                minTickGap={32}
                tickFormatter={(value: string) => formatTick(value, spanOf(data))}
              />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={32} />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(_, payload) => {
                      const start = payload?.[0]?.payload?.start as string | undefined
                      return start ? new Date(start).toLocaleString('fr-FR') : ''
                    }}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar isAnimationActive={false} dataKey="tts_ok" stackId="a" fill="var(--color-tts_ok)" />
              <Bar isAnimationActive={false} dataKey="tts_failed" stackId="a" fill="var(--color-tts_failed)" />
              <Bar isAnimationActive={false} dataKey="stt_streams" stackId="a" fill="var(--color-stt_streams)" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
