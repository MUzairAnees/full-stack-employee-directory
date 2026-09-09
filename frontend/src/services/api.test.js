import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getHealth, apiFetch, authFetch, getToken, onSessionExpired } from './api';

describe('getHealth', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('calls the employee-directory health endpoint and returns the parsed body', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ status: 'ok' }),
    });

    const result = await getHealth();

    // apiFetch always forwards its options param to fetch(), even when
    // undefined — functionally identical (fetch(url, undefined) ===
    // fetch(url)), but that's what the mock actually records.
    expect(fetch).toHaveBeenCalledWith(
      `${import.meta.env.VITE_API_URL}/api/employee-directory/health`,
      undefined,
    );
    expect(result).toEqual({ status: 'ok' });
  });
});

describe('apiFetch (CloudFront 404 backstop, for FastAPI\'s own unmatched-route 404 -- our domain not-found uses 410 and needs no help)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('restores a genuine 404 when CloudFront rewrites it to 200 text/html', async () => {
    // This is the exact shape infra/cloudfront.tf's custom_error_response
    // produces: it substitutes index.html (200, text/html) for any 404,
    // regardless of which origin produced it. This API never legitimately
    // returns HTML, so apiFetch must treat this as the 404 it really is.
    fetch.mockResolvedValueOnce({
      status: 200,
      headers: new Headers({ 'content-type': 'text/html' }),
      json: async () => {
        throw new Error('must not be called: this is index.html, not JSON');
      },
    });

    const response = await apiFetch('/some/unmatched/route');

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ detail: 'Not Found' });
  });

  it('passes through a real JSON response unmodified', async () => {
    const realResponse = {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ id: 1, name: 'Remote' }),
    };
    fetch.mockResolvedValueOnce(realResponse);

    const response = await apiFetch('/work-locations/1');

    expect(response).toBe(realResponse);
  });

  it('passes a genuine 410 (real not-found) through unchanged, not just any JSON', async () => {
    // Our own not-found responses are 410, not 200, so the backstop's
    // status === 200 check must never touch them — proving that
    // explicitly, not just relying on the other tests' inference.
    const real410 = {
      ok: false,
      status: 410,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ detail: 'work location 999999 not found' }),
    };
    fetch.mockResolvedValueOnce(real410);

    const response = await apiFetch('/work-locations/999999');

    expect(response).toBe(real410);
    expect(response.status).toBe(410);
    await expect(response.json()).resolves.toEqual({
      detail: 'work location 999999 not found',
    });
  });
});

describe('authFetch (session-expiry interceptor)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    localStorage.clear();
  });

  it('clears the token and notifies subscribers on a 401 from an authenticated call', async () => {
    // departments is the first real caller of authFetch beyond login
    // itself, so this is the first time an expired/invalid token
    // mid-session is actually reachable — confirming the mechanism
    // works, not just re-reading the code that implements it.
    localStorage.setItem('employee-directory-token', 'some-token');
    fetch.mockResolvedValueOnce({
      status: 401,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ detail: 'not authenticated' }),
    });

    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    await expect(authFetch('/departments')).rejects.toThrow('Your session ended - sign in again');

    expect(getToken()).toBeNull();
    expect(listener).toHaveBeenCalledOnce();

    unsubscribe();
  });
});
