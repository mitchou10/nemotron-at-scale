import { render, screen } from '@testing-library/react'
import { Mic } from 'lucide-react'
import { describe, expect, it } from 'vitest'
import { StatCard } from './stat-card'

describe('StatCard', () => {
  it('shows the label, the value and the hint', () => {
    render(<StatCard label="Flux STT" value="423" hint="60 clients" icon={Mic} />)
    expect(screen.getByText('Flux STT')).toBeInTheDocument()
    expect(screen.getByText('423')).toBeInTheDocument()
    expect(screen.getByText('60 clients')).toBeInTheDocument()
  })

  it('shows a placeholder while the value loads', () => {
    const { container } = render(<StatCard label="Flux STT" value={undefined} icon={Mic} />)
    expect(screen.queryByText('423')).not.toBeInTheDocument()
    expect(container.querySelector('[data-slot="skeleton"]')).toBeInTheDocument()
  })
})
