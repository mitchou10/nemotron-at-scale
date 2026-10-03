const TOKEN_KEY = 'nemotron-admin-token'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable (private window): the token only lives until the next reload
  }
}

/** GET `/api/v1/admin/<path>`, with the admin token when there is one. */
export async function adminGet<T>(path: string, params: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value))
  }
  const suffix = query.size ? `?${query}` : ''
  const token = getToken()
  const response = await fetch(`/api/v1/admin/${path}${suffix}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: 'no-store',
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? body.error?.message ?? detail
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, typeof detail === 'string' ? detail : response.statusText)
  }
  return (await response.json()) as T
}
