import createClient from 'openapi-fetch';
import type { paths } from './schema';

// Base URL handling: normalize trailing slash
const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';
export const BASE_URL = rawBaseUrl.replace(/\/+$/, '');

let authToken: string | null = null;
let userRole: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setUserRole(role: string | null) {
  userRole = role;
}

export function getUserRole(): string | null {
  return userRole;
}

export const client = createClient<paths>({
  baseUrl: BASE_URL,
});

// Attach Authorization and X-User-Role headers to all requests
client.use({
  async onRequest({ request }) {
    if (authToken) {
      request.headers.set('Authorization', `Bearer ${authToken}`);
    }
    if (userRole) {
      request.headers.set('X-User-Role', userRole);
    }
    return request;
  },
});

export default client;

/**
 * Fetch an authenticated document page image and create a blob URL.
 * Automatically attaches Authorization and role headers.
 * Caller should revoke the URL on unmount.
 */
export async function fetchDocumentPageImageUrl(
  uid: string,
  pageNumber: number = 1,
  width?: number
): Promise<{ url: string; revoke: () => void }> {
  const query = width ? `?width=${width}` : '';
  const url = `${BASE_URL}/api/v1/documents/${encodeURIComponent(uid)}/pages/${pageNumber}/image${query}`;

  const headers: Record<string, string> = {};
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  if (userRole) {
    headers['X-User-Role'] = userRole;
  }

  const res = await fetch(url, { headers });
  if (res.status === 401) {
    throw new Error('401 Unauthorized');
  }
  if (res.status === 403) {
    throw new Error('403 Forbidden: Access denied');
  }
  if (!res.ok) {
    throw new Error(`Failed to load page image: ${res.statusText}`);
  }

  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  return {
    url: blobUrl,
    revoke: () => URL.revokeObjectURL(blobUrl),
  };
}

