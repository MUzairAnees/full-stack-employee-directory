import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorkLocations from './WorkLocations';
import * as api from '../services/api';

describe('WorkLocations', () => {
  it('renders a location returned by the API', async () => {
    vi.spyOn(api, 'listWorkLocations').mockResolvedValue([{ id: 1, name: 'Remote' }]);

    render(<WorkLocations />);

    expect(await screen.findByText('Remote')).toBeInTheDocument();
  });

  it('shows an error state when the API call fails, rather than rendering blank', async () => {
    vi.spyOn(api, 'listWorkLocations').mockRejectedValue(
      new Error('Failed to load work locations: 500'),
    );

    render(<WorkLocations />);

    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
