import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PIIMaskedValue } from '../components/PIIMaskedValue';
import { setActiveRole } from '../api/client';

describe('PIIMaskedValue', () => {
  it('masks sensitive PII by default', () => {
    setActiveRole('reviewer');
    render(<PIIMaskedValue value="987-65-4321" piiType="SSN" />);
    expect(screen.queryByText('987-65-4321')).toBeNull();
    expect(screen.getByText(/SSN: ••••••••/)).toBeInTheDocument();
  });

  it('unmasks PII on click for authorized role', () => {
    setActiveRole('reviewer');
    render(<PIIMaskedValue value="Alice Smith" piiType="PERSON" />);
    const toggleButton = screen.getByRole('button');
    fireEvent.click(toggleButton);
    expect(screen.getByText('Alice Smith')).toBeInTheDocument();
  });
});
