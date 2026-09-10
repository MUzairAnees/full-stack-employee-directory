import { useEffect, useState } from 'react';
import { listEmployees } from '../services/api';

/**
 * Lists employees. Read-only this slice - create/edit/delete are all
 * built on the backend (see backend README) but have no UI yet.
 */
function Employees() {
  const [employees, setEmployees] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listEmployees()
      .then(setEmployees)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p>Employees error: {error}</p>;
  }

  if (employees === null) {
    return <p>Loading employees...</p>;
  }

  return (
    <ul>
      {employees.map((employee) => (
        <li key={employee.id}>
          {employee.first_name} {employee.last_name} ({employee.role})
        </li>
      ))}
    </ul>
  );
}

export default Employees;
