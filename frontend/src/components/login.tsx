import { KeyRound } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

export function Login({ onSubmit, error }: { onSubmit: (token: string) => void; error: boolean }) {
  const [token, setToken] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (token.trim()) onSubmit(token.trim())
  }

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="size-4" /> Administration
          </CardTitle>
          <CardDescription>
            Entrez le jeton d'administration (<code>ADMIN_TOKEN</code> du backend).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <Input
              type="password"
              autoFocus
              autoComplete="off"
              placeholder="Jeton"
              aria-label="Jeton d'administration"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            {error && <p className="text-destructive text-sm">Jeton refusé par le backend.</p>}
            <Button type="submit" className="w-full">
              Se connecter
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
