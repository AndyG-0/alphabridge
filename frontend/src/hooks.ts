import { useCallback, useEffect, useState } from 'react'

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  // Caller-supplied deps: intentionally not statically analyzable.
  /* eslint-disable react-hooks/exhaustive-deps, react-hooks/use-memo */
  const run = useCallback(() => {
    setLoading(true)
    fn()
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }, deps)
  /* eslint-enable react-hooks/exhaustive-deps, react-hooks/use-memo */
  useEffect(run, [run])
  return { data, error, loading, reload: run }
}
