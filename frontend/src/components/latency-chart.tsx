import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { formatMs, formatTick, spanOf } from '@/lib/format'
import type { Timeseries } from '@/lib/types'

const config = {
  tts_avg_duration_ms: { label: 'Durée moyenne', color: 'var(--chart-4)' },
} satisfies ChartConfig

export function LatencyChart({ data }: { data: Timeseries | undefined }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Durée des synthèses</CardTitle>
        <CardDescription>Durée moyenne d'une requête TTS réussie, par tranche de temps.</CardDescription>
      </CardHeader>
      <CardContent>
        {!data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <ChartContainer config={config} className="h-64 w-full">
            <AreaChart data={data.buckets} margin={{ left: 0, right: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="start"
                tickLine={false}
                axisLine={false}
                minTickGap={32}
                tickFormatter={(value: string) => formatTick(value, spanOf(data))}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={64}
                tickFormatter={(value: number) => formatMs(value)}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value) => formatMs(typeof value === 'number' ? value : null)}
                  />
                }
              />
              <Area
                isAnimationActive={false}
                dataKey="tts_avg_duration_ms"
                type="monotone"
                stroke="var(--color-tts_avg_duration_ms)"
                fill="var(--color-tts_avg_duration_ms)"
                fillOpacity={0.2}
                connectNulls
              />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
