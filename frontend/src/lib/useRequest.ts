/** Expose explicit request loading/error state without fetching during render. */
import { useCallback, useState } from 'react';
/** Track an activated asynchronous operation and propagate failures to its caller. */
export function useRequest() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(operation: () => Promise<T>): Promise<T> => {
    setLoading(true);
    setError(null);
    try { return await operation(); }
    catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Request failed. Try again.');
      throw failure;
    } finally { setLoading(false); }
  }, []);
  return { loading, error, run };
}
