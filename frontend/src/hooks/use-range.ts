import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { findRange, type Range } from '@/lib/range'

/** The period selected in the header, kept in the URL (`?range=7d`) so it can be shared. */
export function useRange(): [Range, (id: string) => void] {
  const [params, setParams] = useSearchParams()
  const range = findRange(params.get('range'))
  const setRange = useCallback(
    (id: string) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          next.set('range', id)
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  return [range, setRange]
}
