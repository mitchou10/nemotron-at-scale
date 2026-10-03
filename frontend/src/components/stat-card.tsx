import type { LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface StatCardProps {
  label: string
  value: string | undefined
  hint?: string
  icon: LucideIcon
  tone?: 'default' | 'good' | 'bad' | 'warn'
}

const TONES = {
  default: 'bg-muted text-muted-foreground',
  good: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  bad: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
  warn: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
} as const

export function StatCard({ label, value, hint, icon: Icon, tone = 'default' }: StatCardProps) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="text-muted-foreground truncate text-sm">{label}</p>
          {value === undefined ? (
            <Skeleton className="h-8 w-24" />
          ) : (
            <p className="text-2xl font-semibold tabular-nums">{value}</p>
          )}
          {hint && <p className="text-muted-foreground truncate text-xs">{hint}</p>}
        </div>
        <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', TONES[tone])}>
          <Icon className="size-4" />
        </span>
      </CardContent>
    </Card>
  )
}
