import { afterEach, describe, expect, it, vi } from 'vitest'
import { adminGet, ApiError, getToken, setToken } from './api'

function reply(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('token', () => {
  it('is kept for the session and can be removed', () => {
    expect(getToken()).toBeNull()
    setToken('abc')
    expect(getToken()).toBe('abc')
    setToken(null)
    expect(getToken()).toBeNull()
  })
})

describe('adminGet', () => {
  it('calls the admin API with the query and the token', async () => {
    const fetchMock = reply(200, { ok: true })
    vi.stubGlobal('fetch', fetchMock)
    setToken('secret')

    await expect(adminGet('overview', { hours: 24, state: undefined })).resolves.toEqual({ ok: true })

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/admin/overview?hours=24')
    expect(options.headers).toEqual({ Authorization: 'Bearer secret' })
  })

  it('sends no Authorization header without a token', async () => {
    const fetchMock = reply(200, [])
    vi.stubGlobal('fetch', fetchMock)
    await adminGet('workers')
    expect(fetchMock.mock.calls[0][1].headers).toEqual({})
  })

  it('raises an ApiError with the status and the message of the backend', async () => {
    vi.stubGlobal('fetch', reply(401, { detail: 'invalid or missing admin token' }))
    const error = await adminGet('overview').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(401)
    expect((error as ApiError).message).toBe('invalid or missing admin token')
  })

  it('understands the OpenAI-shaped errors too', async () => {
    vi.stubGlobal('fetch', reply(503, { error: { message: 'unavailable' } }))
    await expect(adminGet('overview')).rejects.toThrow('unavailable')
  })
})
