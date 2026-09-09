import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getHealth } from './api';

describe('getHealth', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('calls the employee-directory health endpoint and returns the parsed body', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'ok' }),
    });

    const result = await getHealth();

    expect(fetch).toHaveBeenCalledWith(
      `${import.meta.env.VITE_API_URL}/api/employee-directory/health`,
    );
    expect(result).toEqual({ status: 'ok' });
  });
});
