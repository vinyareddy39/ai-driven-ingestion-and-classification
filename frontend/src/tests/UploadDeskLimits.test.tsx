import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { UploadDesk } from '../components/UploadDesk';
import { client } from '../api/client';

describe('UploadDesk Limits and Friendly Error Messages (Step 4 & 5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('validates oversized files and displays friendly error message before upload', async () => {
    vi.spyOn(client, 'GET').mockResolvedValueOnce({
      data: {
        max_upload_mb: 200,
        max_upload_size_mb: 200,
        max_upload_size_bytes: 200 * 1024 * 1024,
        allowed_file_types: ['application/pdf', 'image/png'],
        allowed_extensions: ['.pdf', '.png'],
      },
      error: null,
      response: new Response(),
    } as any);

    render(<UploadDesk />);

    // Wait for limits to load
    await waitFor(() => {
      expect(screen.getByText(/Max 200 MB/i)).toBeInTheDocument();
    });

    // Create a synthetic 230 MB file
    const oversizedFile = new File([new Uint8Array(10)], 'large_document.pdf', {
      type: 'application/pdf',
    });
    Object.defineProperty(oversizedFile, 'size', {
      value: 230 * 1024 * 1024,
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [oversizedFile] } });

    // Verify friendly error message
    await waitFor(() => {
      expect(
        screen.getByText('File is 230 MB. Maximum allowed is 200 MB.')
      ).toBeInTheDocument();
    });
  });

  it('rejects unsupported file types before upload', async () => {
    vi.spyOn(client, 'GET').mockResolvedValueOnce({
      data: {
        max_upload_mb: 200,
        max_upload_size_mb: 200,
        max_upload_size_bytes: 200 * 1024 * 1024,
        allowed_file_types: ['application/pdf'],
        allowed_extensions: ['.pdf'],
      },
      error: null,
      response: new Response(),
    } as any);

    render(<UploadDesk />);

    await waitFor(() => {
      expect(screen.getByText(/Max 200 MB/i)).toBeInTheDocument();
    });

    const invalidFile = new File(['binary content'], 'script.exe', {
      type: 'application/x-msdownload',
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [invalidFile] } });

    await waitFor(() => {
      expect(screen.getByText(/File type not allowed/i)).toBeInTheDocument();
    });
  });
});
