import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Teams from './Teams';
import * as api from '../services/api';

describe('Teams', () => {
  it('renders a team returned by the API', async () => {
    vi.spyOn(api, 'listTeams').mockResolvedValue([{ id: 1, name: 'Platform' }]);

    render(<Teams />);

    expect(await screen.findByText('Platform')).toBeInTheDocument();
  });

  it('shows an error state when the API call fails, rather than rendering blank', async () => {
    vi.spyOn(api, 'listTeams').mockRejectedValue(new Error('Failed to load teams: 500'));

    render(<Teams />);

    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
