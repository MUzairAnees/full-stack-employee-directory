import { useEffect, useState } from 'react';
import { listSkills } from '../services/api';

/**
 * Lists skills. Read-only this slice - attach/detach are built on the
 * backend (see backend README) but have no UI yet; per-employee skills
 * display is deferred, this is the lookup list only.
 */
function Skills() {
  const [skills, setSkills] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listSkills()
      .then(setSkills)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>Skills error: {error}</p>;
  }

  if (skills === null) {
    return <p>Loading skills...</p>;
  }

  return (
    <ul>
      {skills.map((skill) => (
        <li key={skill.id}>{skill.name}</li>
      ))}
    </ul>
  );
}

export default Skills;
