import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Employees from './Employees';
import * as api from '../services/api';

describe('Employees', () => {
  it('renders an employee returned by the API', async () => {
    vi.spyOn(api, 'listEmployees').mockResolvedValue([
      { id: 1, first_name: 'Demo', last_name: 'CEO', role: 'CEO' },
    ]);

    render(<Employees />);

    expect(await screen.findByText('Demo CEO (CEO)')).toBeInTheDocument();
  });

  it('shows an error state when the API call fails, rather than rendering blank', async () => {
    vi.spyOn(api, 'listEmployees').mockRejectedValue(new Error('Failed to load employees: 500'));

    render(<Employees />);

    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
