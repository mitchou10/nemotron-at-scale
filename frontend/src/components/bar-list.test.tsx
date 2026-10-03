import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarList } from './bar-list'

describe('BarList', () => {
  it('lists every item with its count', () => {
    render(<BarList title="Voix" items={[{ name: 'fr_FR-siwis-medium', count: 1185 }, { name: 'en', count: 3 }]} />)
    expect(screen.getByText('fr_FR-siwis-medium')).toBeInTheDocument()
    expect(screen.getByText(/1.185/)).toBeInTheDocument()
  })

  it('says when there is nothing', () => {
    render(<BarList title="Voix" items={[]} />)
    expect(screen.getByText('Aucune donnée sur la période.')).toBeInTheDocument()
  })
})
