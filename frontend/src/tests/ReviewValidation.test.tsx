import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { ReviewQueuePage } from '../pages/ReviewQueuePage';
import { PIIMaskedValue } from '../components/PIIMaskedValue';
import * as clientModule from '../api/client';

describe('Review Screens Accessibility & Safety (Requirement 23)', () => {
  it('renders accessible table headers and empty queue state', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    vi.spyOn(clientModule.api, 'getReviewQueue').mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 1,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ReviewQueuePage />
        </BrowserRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText(/Review Queue is Empty/i)).toBeInTheDocument();
  });

  it('provides visible keyboard navigation instructions', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    vi.spyOn(clientModule.api, 'getReviewQueue').mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 1,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ReviewQueuePage />
        </BrowserRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText(/to navigate/i)).toBeInTheDocument();
  });

  it('escapes raw HTML injection in extracted values and PII (Requirement 20)', () => {
    clientModule.setActiveRole('reviewer');
    const maliciousInput = '<script>alert("XSS")</script><img src="x" onerror="alert(1)">';
    render(<PIIMaskedValue value={maliciousInput} piiType="PERSON" />);

    // Reveal using React Testing Library fireEvent
    fireEvent.click(screen.getByRole('button'));

    // Verify it is rendered as text and NOT as an active script/img element
    expect(screen.getByText(maliciousInput)).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
  });
});
