import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Login } from './login'

describe('Login', () => {
  it('sends the typed token, trimmed', async () => {
    const onSubmit = vi.fn()
    render(<Login onSubmit={onSubmit} error={false} />)
    await userEvent.type(screen.getByLabelText("Jeton d'administration"), '  s3cret ')
    await userEvent.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(onSubmit).toHaveBeenCalledWith('s3cret')
  })

  it('sends nothing for an empty token', async () => {
    const onSubmit = vi.fn()
    render(<Login onSubmit={onSubmit} error={false} />)
    await userEvent.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('says when the token was refused', () => {
    render(<Login onSubmit={vi.fn()} error />)
    expect(screen.getByText('Jeton refusé par le backend.')).toBeInTheDocument()
  })
})
