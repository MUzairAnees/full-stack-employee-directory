import { useState } from 'react';
import { Alert, Button, Card, CardContent, CircularProgress, Stack, TextField, Typography } from '@mui/material';
import { getMe, login } from '../services/api';
import { useCurrentUser } from '../context/CurrentUserContext';

/**
 * Login form. On success, populates the shared current-user context
 * directly via /me (so the freshest role/is_active is what the rest of
 * the app sees) rather than requiring a parent to pass a callback down.
 */
function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const { setCurrentUser } = useCurrentUser();

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      const me = await getMe();
      setCurrentUser(me);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card sx={{ maxWidth: 360, mx: 'auto', mt: 8 }}>
      <CardContent>
        <Typography variant="h5" component="h1" gutterBottom>
          Sign in
        </Typography>
        <form onSubmit={handleSubmit}>
          <Stack spacing={2}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              fullWidth
            />
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              fullWidth
            />
            <Button
              type="submit"
              variant="contained"
              disabled={submitting}
              fullWidth
              startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : null}
            >
              {submitting ? 'Signing in...' : 'Sign in'}
            </Button>
          </Stack>
        </form>
      </CardContent>
    </Card>
  );
}

export default Login;
