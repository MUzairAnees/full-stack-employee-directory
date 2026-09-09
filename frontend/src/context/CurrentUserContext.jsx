import { createContext, useContext, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { clearToken, getMe, getToken, onSessionExpired } from '../services/api';

const CurrentUserContext = createContext(undefined);

/**
 * Provides the authenticated employee (or null) to the whole app via
 * context rather than local state — by the time role-gated pages and
 * Admin-only buttons exist, several components need "who am I", and
 * context avoids prop-drilling it to each one.
 *
 * On mount, if a token is stored, calls /me to validate it AND re-read
 * the employee from the database — a deactivated account is rejected on
 * the next load, not just at token expiry. Also subscribes to api.js's
 * session-expired pub-sub: the one place a 401 from any later
 * authenticated call clears the token; this just reacts to that
 * notification by resetting state, since api.js itself can't touch React.
 *
 * @param {{children: import('react').ReactNode}} props
 */
export function CurrentUserProvider({ children }) {
  // undefined = still checking on first load; null = signed out;
  // object = the employee from /me.
  const [currentUser, setCurrentUser] = useState(undefined);

  useEffect(() => onSessionExpired(() => setCurrentUser(null)), []);

  useEffect(() => {
    if (!getToken()) {
      setCurrentUser(null);
      return;
    }
    getMe()
      .then(setCurrentUser)
      .catch(() => setCurrentUser(null));
  }, []);

  function logout() {
    clearToken();
    setCurrentUser(null);
  }

  return (
    <CurrentUserContext.Provider value={{ currentUser, setCurrentUser, logout }}>
      {children}
    </CurrentUserContext.Provider>
  );
}

CurrentUserProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

/**
 * @returns {{
 *   currentUser: object|null|undefined,
 *   setCurrentUser: (user: object|null) => void,
 *   logout: () => void,
 * }} currentUser is undefined while the initial /me check is in flight.
 */
export function useCurrentUser() {
  return useContext(CurrentUserContext);
}
