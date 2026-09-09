import { useEffect, useState } from 'react';
import { listWorkLocations } from '../services/api';

/**
 * Lists work locations fetched from the real API. This is what proves the
 * chain end to end with actual data, not a static string.
 */
function WorkLocations() {
  const [locations, setLocations] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listWorkLocations()
      .then(setLocations)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>Work locations error: {error}</p>;
  }

  if (locations === null) {
    return <p>Loading work locations...</p>;
  }

  return (
    <ul>
      {locations.map((location) => (
        <li key={location.id}>{location.name}</li>
      ))}
    </ul>
  );
}

export default WorkLocations;
