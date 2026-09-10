import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Projects from './Projects';
import * as api from '../services/api';

describe('Projects', () => {
  it('renders a project returned by the API', async () => {
    vi.spyOn(api, 'listProjects').mockResolvedValue([{ id: 1, name: 'Atlas', description: 'A big rewrite' }]);

    render(<Projects />);

    expect(await screen.findByText('Atlas - A big rewrite')).toBeInTheDocument();
  });

  it('renders a project with no description without a trailing dash', async () => {
    vi.spyOn(api, 'listProjects').mockResolvedValue([{ id: 1, name: 'Atlas', description: null }]);

    render(<Projects />);

    expect(await screen.findByText('Atlas')).toBeInTheDocument();
  });

  it('shows an error state when the API call fails, rather than rendering blank', async () => {
    vi.spyOn(api, 'listProjects').mockRejectedValue(new Error('Failed to load projects: 500'));

    render(<Projects />);

    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
