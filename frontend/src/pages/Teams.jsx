import { useEffect, useState } from 'react';
import { listTeams } from '../services/api';

/**
 * Lists teams. Read-only this slice - create/replace-manager/delete are
 * all built on the backend (see backend README) but have no UI yet.
 */
function Teams() {
  const [teams, setTeams] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listTeams()
      .then(setTeams)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>Teams error: {error}</p>;
  }

  if (teams === null) {
    return <p>Loading teams...</p>;
  }

  return (
    <ul>
      {teams.map((team) => (
        <li key={team.id}>{team.name}</li>
      ))}
    </ul>
  );
}

export default Teams;
