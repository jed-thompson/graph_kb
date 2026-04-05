import { render, screen } from '@testing-library/react';
import { StatusBadge } from '../badge';

describe('StatusBadge', () => {
  it('renders pending status', () => {
    render(<StatusBadge status="pending" />);
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('renders indexing status', () => {
    render(<StatusBadge status="indexing" />);
    expect(screen.getByText('Indexing')).toBeInTheDocument();
  });

  it('renders ready status', () => {
    render(<StatusBadge status="ready" />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('renders error status', () => {
    render(<StatusBadge status="error" />);
    expect(screen.getByText('Error')).toBeInTheDocument();
  });
});
