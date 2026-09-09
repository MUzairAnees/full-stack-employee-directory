import { useEffect, useState } from 'react';
import { listDepartments } from '../services/api';

/**
 * Lists departments. Read-only this slice — create/rename/restore/
 * delete are CEO-only backend operations with no UI yet.
 */
function Departments() {
  const [departments, setDepartments] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listDepartments()
      .then(setDepartments)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>Departments error: {error}</p>;
  }

  if (departments === null) {
    return <p>Loading departments...</p>;
  }

  return (
    <ul>
      {departments.map((department) => (
        <li key={department.id}>{department.name}</li>
      ))}
    </ul>
  );
}

export default Departments;
