import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConfidenceBadge } from '../components/ConfidenceBadge';

describe('ConfidenceBadge', () => {
  it('renders emerald badge for high confidence >= 90%', () => {
    render(<ConfidenceBadge confidence={0.96} />);
    const badge = screen.getByTestId('confidence-badge');
    expect(badge).toHaveTextContent('96%');
    expect(badge.className).toContain('emerald');
  });

  it('renders amber badge for medium confidence between 75% and 89%', () => {
    render(<ConfidenceBadge confidence={0.82} />);
    const badge = screen.getByTestId('confidence-badge');
    expect(badge).toHaveTextContent('82%');
    expect(badge.className).toContain('amber');
  });

  it('renders rose badge for low confidence < 75%', () => {
    render(<ConfidenceBadge confidence={0.61} />);
    const badge = screen.getByTestId('confidence-badge');
    expect(badge).toHaveTextContent('61%');
    expect(badge.className).toContain('rose');
  });

  it('handles percentage input values > 1.0 (e.g. 95)', () => {
    render(<ConfidenceBadge confidence={95} />);
    const badge = screen.getByTestId('confidence-badge');
    expect(badge).toHaveTextContent('95%');
  });
});
