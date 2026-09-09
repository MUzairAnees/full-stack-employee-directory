import { useEffect, useState } from 'react';
import { getHealth } from './services/api';

/**
 * Root component for slice 0. Its only job is to prove the full local
 * chain works: browser -> CORS proxy (3001) -> LocalStack Lambda Function
 * URL -> FastAPI. It calls the health endpoint on mount and renders
 * whatever comes back, plainly, so a broken chain is obvious on screen.
 */
function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getHealth()
      .then((data) => setStatus(data.status))
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>API error: {error}</p>;
  }

  return <p>API: {status ?? 'loading...'}</p>;
}

export default App;
