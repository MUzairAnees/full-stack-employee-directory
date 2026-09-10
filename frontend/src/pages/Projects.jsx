import { useEffect, useState } from 'react';
import { listProjects } from '../services/api';

/**
 * Lists projects. Read-only this slice - attach/complete/detach and
 * team achievements are built on the backend (see backend README) but
 * have no UI yet; per-employee projects display is deferred, same as
 * skills, this is the lookup list only.
 */
function Projects() {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>Projects error: {error}</p>;
  }

  if (projects === null) {
    return <p>Loading projects...</p>;
  }

  return (
    <ul>
      {projects.map((project) => (
        <li key={project.id}>
          {project.name}
          {project.description ? ` - ${project.description}` : ''}
        </li>
      ))}
    </ul>
  );
}

export default Projects;
