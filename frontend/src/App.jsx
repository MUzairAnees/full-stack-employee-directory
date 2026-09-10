import { useEffect, useState } from 'react';
import { AppBar, Box, Button, CircularProgress, Toolbar, Typography } from '@mui/material';
import { getHealth } from './services/api';
import WorkLocations from './pages/WorkLocations';
import Departments from './pages/Departments';
import Employees from './pages/Employees';
import Teams from './pages/Teams';
import Skills from './pages/Skills';
import Login from './pages/Login';
import { useCurrentUser } from './context/CurrentUserContext';

/**
 * Root component. Still no router (one real page doesn't need one yet) —
 * signed-in state alone decides what renders: Login, or the app content
 * with a "signed in as <name> (<role>)" line and a Sign out button.
 */
function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const { currentUser, logout } = useCurrentUser();

  useEffect(() => {
    getHealth()
      .then((data) => setStatus(data.status))
      .catch((err) => setError(err.message));
  }, []);

  if (currentUser === undefined) {
    return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 8 }} />;
  }

  if (!currentUser) {
    return <Login />;
  }

  return (
    <>
      <AppBar position="static">
        <Toolbar sx={{ justifyContent: 'space-between' }}>
          <Typography>
            Signed in as {currentUser.first_name} {currentUser.last_name} ({currentUser.role})
          </Typography>
          <Button color="inherit" onClick={logout}>
            Sign out
          </Button>
        </Toolbar>
      </AppBar>
      <Box sx={{ p: 2 }}>
        <p>API: {error ? `error: ${error}` : (status ?? 'loading...')}</p>
        <Typography variant="h5" component="h1">
          Work Locations
        </Typography>
        <WorkLocations />
        <Typography variant="h5" component="h1" sx={{ mt: 2 }}>
          Departments
        </Typography>
        <Departments />
        <Typography variant="h5" component="h1" sx={{ mt: 2 }}>
          Employees
        </Typography>
        <Employees />
        <Typography variant="h5" component="h1" sx={{ mt: 2 }}>
          Teams
        </Typography>
        <Teams />
        <Typography variant="h5" component="h1" sx={{ mt: 2 }}>
          Skills
        </Typography>
        <Skills />
      </Box>
    </>
  );
}

export default App;
