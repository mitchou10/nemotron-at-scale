import { TriangleAlert } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'

export function ErrorState({ error }: { error: Error }) {
  return (
    <Card className="border-destructive/40">
      <CardContent className="text-destructive flex items-center gap-2 text-sm">
        <TriangleAlert className="size-4 shrink-0" />
        Impossible de charger les données : {error.message}
      </CardContent>
    </Card>
  )
}
