/**
 * Base URL for every backend call. This one line is the entire environment
 * story: locally it resolves through the CORS proxy (bin/proxy-server.js,
 * port 3001), which strips the "/api/employee-directory" prefix before
 * forwarding to the LocalStack Lambda Function URL. On AWS it resolves
 * through CloudFront, whose "/api/employee-directory*" cache behavior
 * forwards the full, unstripped path to the same Lambda, which strips the
 * prefix itself (see backend/employee-directory/function.py). No branching
 * needed here.
 */
const BASE_URL = `${import.meta.env.VITE_API_URL}/api/employee-directory`;

const TOKEN_STORAGE_KEY = 'employee-directory-token';

// ---------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------

/** @returns {string|null} The stored token, or null if there isn't one. */
export function getToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setToken(token) {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Private browsing / storage disabled: login still works for this
    // page load, it just won't survive a refresh.
  }
}

/** Clears the stored token. Safe to call even if there isn't one. */
export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------
// Session-expired pub-sub
// ---------------------------------------------------------------------
// api.js can't import React, so React-side code (CurrentUserContext)
// subscribes to this instead of us reaching into component state
// directly. This is ONLY for the automatic case (a 401 from an
// authenticated call, handled in authFetch below) — voluntary sign-out
// is a direct user action already inside a component and doesn't need
// to go through here.

const sessionExpiredListeners = new Set();

/**
 * Subscribes to session-expiry notifications.
 *
 * @param {() => void} callback
 * @returns {() => void} Unsubscribe function.
 */
export function onSessionExpired(callback) {
  sessionExpiredListeners.add(callback);
  return () => sessionExpiredListeners.delete(callback);
}

function notifySessionExpired() {
  for (const callback of sessionExpiredListeners) callback();
}

// ---------------------------------------------------------------------
// Error taxonomy
// ---------------------------------------------------------------------
// Login alone needs to tell wrong-credentials apart from session-expired
// apart from forbidden apart from server error apart from network-down.
// Building this now, in one place, so "not found" is one more case when
// detail views arrive later, not a new pattern invented then.

export const ErrorKind = {
  WRONG_CREDENTIALS: 'WRONG_CREDENTIALS',
  SESSION_EXPIRED: 'SESSION_EXPIRED',
  FORBIDDEN: 'FORBIDDEN',
  SERVER_ERROR: 'SERVER_ERROR',
  NETWORK_ERROR: 'NETWORK_ERROR',
};

const MESSAGES = {
  [ErrorKind.WRONG_CREDENTIALS]: 'Incorrect email or password',
  [ErrorKind.SESSION_EXPIRED]: 'Your session ended - sign in again',
  [ErrorKind.FORBIDDEN]: "You don't have permission",
  [ErrorKind.SERVER_ERROR]: 'Something went wrong',
  [ErrorKind.NETWORK_ERROR]: "Can't reach the server",
};

export class ApiError extends Error {
  /**
   * @param {string} kind One of ErrorKind.
   * @param {number} [status] The HTTP status, if there was one.
   */
  constructor(kind, status) {
    super(MESSAGES[kind]);
    this.kind = kind;
    this.status = status;
  }
}

/**
 * Classifies a non-ok response into an ApiError. Covers what's generic
 * across any call; callers that need a more specific classification for
 * a particular status (like login's own 401) check that before falling
 * back to this.
 *
 * @param {Response} response
 * @returns {ApiError}
 */
function classifyError(response) {
  if (response.status === 403) return new ApiError(ErrorKind.FORBIDDEN, response.status);
  return new ApiError(ErrorKind.SERVER_ERROR, response.status);
}

// ---------------------------------------------------------------------
// Fetch wrappers
// ---------------------------------------------------------------------

/**
 * Fetches from the API and restores real HTTP semantics where the
 * *provided* CloudFront distribution silently rewrites them.
 *
 * This is a BACKSTOP, not the fix. Per workshop guidance, our own
 * domain-level not-found responses use 410 Gone instead of 404 (see
 * app/main.py's exception handler and the backend README) precisely
 * because 404 is reserved by the platform — so those no longer need this
 * function's help; a 410 passes through CloudFront untouched. What's left
 * for this to catch is FastAPI's own native 404 for genuinely unmatched
 * routes, which we don't raise and can't redirect to 410 the way we did
 * our own exception. infra/cloudfront.tf's custom_error_response maps
 * 404 -> 200 /index.html distribution-wide (meant for SPA deep-link
 * fallback, not scoped to a cache behavior), so an unmatched route still
 * arrives at the browser as a 200 HTML page. Confirmed against
 * infra/cloudfront.tf: only 404 is mapped this way, not 403 — so 403
 * (permission denials) needs no such backstop. This API never
 * legitimately returns HTML, so a 200 whose content-type isn't JSON is
 * unambiguously that rewrite, not a real response.
 *
 * Also classifies network failures (fetch() itself throwing — DNS,
 * connection refused, offline) as ApiError NETWORK_ERROR, so every
 * caller gets one consistent error shape regardless of where things
 * broke.
 *
 * @param {string} path - Path under BASE_URL, e.g. "/health".
 * @param {RequestInit} [options]
 * @returns {Promise<Response>} The response, with CloudFront's SPA
 *   fallback undone if it fired. Note this does not throw on a 4xx/5xx —
 *   callers check response.ok/status themselves, same as raw fetch.
 */
export async function apiFetch(path, options) {
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, options);
  } catch {
    throw new ApiError(ErrorKind.NETWORK_ERROR);
  }

  const looksLikeCloudFrontSpaFallback =
    response.status === 200 && !response.headers.get('content-type')?.includes('application/json');

  if (looksLikeCloudFrontSpaFallback) {
    return new Response(JSON.stringify({ detail: 'Not Found' }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    });
  }

  return response;
}

/**
 * Like apiFetch, but attaches the stored auth token and treats a 401 as
 * "session expired" — clearing the token and notifying subscribers
 * (CurrentUserContext) before the caller ever sees it. This is the ONE
 * place session expiry is handled; every authenticated call goes through
 * here rather than each reimplementing the same check. Unlike apiFetch,
 * this DOES throw — on a 401, since there is nothing more for the caller
 * to meaningfully do with that response.
 *
 * @param {string} path
 * @param {RequestInit} [options]
 * @returns {Promise<Response>}
 * @throws {ApiError} SESSION_EXPIRED on a 401.
 */
export async function authFetch(path, options = {}) {
  const token = getToken();
  const response = await apiFetch(path, {
    ...options,
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
  });

  if (response.status === 401) {
    clearToken();
    notifySessionExpired();
    throw new ApiError(ErrorKind.SESSION_EXPIRED, 401);
  }

  return response;
}

// ---------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------

/**
 * Logs in and stores the token on success.
 *
 * @param {string} email
 * @param {string} password
 * @returns {Promise<void>}
 * @throws {ApiError} WRONG_CREDENTIALS on 401 — here, and only here, 401
 *   means the credentials were wrong, not that a session expired (there
 *   was no session yet to expire).
 */
export async function login(email, password) {
  const response = await apiFetch('/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (response.status === 401) {
    throw new ApiError(ErrorKind.WRONG_CREDENTIALS, 401);
  }
  if (!response.ok) {
    throw classifyError(response);
  }

  const { access_token: token } = await response.json();
  setToken(token);
}

/**
 * Returns the authenticated employee's basic info. Re-reads the database
 * every call (it's a real request, not a JWT-payload read), so a
 * deactivated account is caught on the next call rather than only at
 * token expiry.
 *
 * @returns {Promise<{id: number, first_name: string, last_name: string, email: string, role: string}>}
 * @throws {ApiError} SESSION_EXPIRED (via authFetch) if not authenticated.
 */
export async function getMe() {
  const response = await authFetch('/me');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

// ---------------------------------------------------------------------
// Other endpoints
// ---------------------------------------------------------------------

/**
 * Calls the service's liveness endpoint.
 *
 * @returns {Promise<{status: string}>} The parsed JSON response body.
 */
export async function getHealth() {
  const response = await apiFetch('/health');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

/**
 * Lists every work location. Requires authentication — the backend
 * closed a slice-1-era gap where this endpoint had no auth dependency
 * (see backend README); this call follows that through authFetch now.
 *
 * @returns {Promise<Array<{id: number, name: string}>>} The work locations.
 */
export async function listWorkLocations() {
  const response = await authFetch('/work-locations');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

/**
 * Lists departments. Requires authentication — goes through authFetch,
 * so an expired/invalid token here triggers the same session-expiry
 * handling as any other authenticated call.
 *
 * @returns {Promise<Array<{id: number, name: string, is_active: boolean}>>}
 */
export async function listDepartments() {
  const response = await authFetch('/departments');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

/**
 * Lists employees.
 *
 * @returns {Promise<Array<{id: number, first_name: string, last_name: string, role: string, is_active: boolean}>>}
 */
export async function listEmployees() {
  const response = await authFetch('/employees');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

/**
 * Lists teams.
 *
 * @returns {Promise<Array<{id: number, name: string, department_id: number, manager_id: number, is_active: boolean}>>}
 */
export async function listTeams() {
  const response = await authFetch('/teams');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

/**
 * Lists skills — the shared lookup list.
 *
 * @returns {Promise<Array<{id: number, name: string}>>}
 */
export async function listSkills() {
  const response = await authFetch('/skills');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}

/**
 * Lists projects — the shared lookup list.
 *
 * @returns {Promise<Array<{id: number, name: string, description: string|null}>>}
 */
export async function listProjects() {
  const response = await authFetch('/projects');
  if (!response.ok) {
    throw classifyError(response);
  }
  return response.json();
}
