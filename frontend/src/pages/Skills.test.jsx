import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Skills from './Skills';
import * as api from '../services/api';

describe('Skills', () => {
  it('renders a skill returned by the API', async () => {
    vi.spyOn(api, 'listSkills').mockResolvedValue([{ id: 1, name: 'Python' }]);

    render(<Skills />);

    expect(await screen.findByText('Python')).toBeInTheDocument();
  });

  it('shows an error state when the API call fails, rather than rendering blank', async () => {
    vi.spyOn(api, 'listSkills').mockRejectedValue(new Error('Failed to load skills: 500'));

    render(<Skills />);

    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
