import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatInt } from '@/lib/format'

interface BarListProps {
  title: string
  items: { name: string; count: number }[]
  empty?: string
}

/** Horizontal bars, longest first: "who got how many calls". */
export function BarList({ title, items, empty = 'Aucune donnée sur la période.' }: BarListProps) {
  const max = Math.max(1, ...items.map((i) => i.count))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.length === 0 && <p className="text-muted-foreground text-sm">{empty}</p>}
        {items.map((item) => (
          <div key={item.name} className="space-y-1">
            <div className="flex justify-between gap-2 text-sm">
              <span className="truncate font-mono text-xs">{item.name}</span>
              <span className="tabular-nums">{formatInt(item.count)}</span>
            </div>
            <div className="bg-muted h-1.5 overflow-hidden rounded-full">
              <div className="bg-chart-1 h-full rounded-full" style={{ width: `${(item.count / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
