import { describe, it, expect, beforeEach } from 'vitest';
import {
  BASE_URL,
  setAuthToken,
  getAuthToken,
  setUserRole,
  getUserRole,
  client,
} from '../api/client';

describe('client auth and config (FIXTURE)', () => {
  beforeEach(() => {
    setAuthToken(null);
    setUserRole(null);
  });

  it('normalizes base url without trailing slash', () => {
    expect(BASE_URL.endsWith('/')).toBe(false);
  });

  it('sets and gets auth token correctly', () => {
    expect(getAuthToken()).toBeNull();
    setAuthToken('FIXTURE_BEARER_TOKEN_XYZ');
    expect(getAuthToken()).toBe('FIXTURE_BEARER_TOKEN_XYZ');
  });

  it('sets and gets user role correctly (LOCAL MODE)', () => {
    expect(getUserRole()).toBeNull();
    setUserRole('admin');
    expect(getUserRole()).toBe('admin');
  });

  it('client instance is configured and has HTTP method functions', () => {
    expect(client).toBeDefined();
    expect(typeof client.GET).toBe('function');
    expect(typeof client.POST).toBe('function');
  });
});
