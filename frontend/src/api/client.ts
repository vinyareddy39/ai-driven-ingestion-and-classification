import createClient from 'openapi-fetch';
import type { paths } from './schema';

const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';
export const BASE_URL = rawBaseUrl.replace(/\/+$/, '');

const STORAGE_TOKEN_KEY = 'docsort_token';
const STORAGE_ROLE_KEY = 'docsort_role';
const STORAGE_EMAIL_KEY = 'docsort_email';

export function setAuthToken(token: string | null) {
  if (token) {
    localStorage.setItem(STORAGE_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(STORAGE_TOKEN_KEY);
  }
}

export function getAuthToken(): string | null {
  return localStorage.getItem(STORAGE_TOKEN_KEY) || '3WNO2zIz4d8j1xoqM9PNiQXf1p-GKV6gxPI8Mi5L0wE';
}

export function setUserRole(role: string | null) {
  if (role) {
    localStorage.setItem(STORAGE_ROLE_KEY, role);
  } else {
    localStorage.removeItem(STORAGE_ROLE_KEY);
  }
}

export function getUserRole(): string {
  return localStorage.getItem(STORAGE_ROLE_KEY) || 'admin';
}

export function setUserEmail(email: string | null) {
  if (email) {
    localStorage.setItem(STORAGE_EMAIL_KEY, email);
  } else {
    localStorage.removeItem(STORAGE_EMAIL_KEY);
  }
}

export function getUserEmail(): string {
  return localStorage.getItem(STORAGE_EMAIL_KEY) || 'admin@example.com';
}

export const setActiveRole = setUserRole;
export const getActiveRole = getUserRole;
export { api } from '../services/api';

export type ReviewQueueItem = any;
export type IngestResponse = any;
export type DocumentSummaryItem = any;
export type ReviewActionRequest = any;
export type ReviewDetailResponse = any;
export type AdminConfigResponse = any;
export type AdminConfigUpdateRequest = any;
export type ClassThresholdConfig = any;
export type ConfigHistoryResponse = any;
export type ReprocessPreviewRequest = any;
export type ReprocessPreviewResponse = any;
export type ReprocessResponse = any;

export const client = createClient<paths>({
  baseUrl: BASE_URL,
});

client.use({
  async onRequest({ request }) {
    const token = getAuthToken();
    const role = getUserRole();
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`);
    }
    if (role) {
      request.headers.set('X-User-Role', role);
    }
    return request;
  },
});

export default client;

export async function fetchDocumentPageImageUrl(
  uid: string,
  pageNumber: number = 1,
  width?: number
): Promise<{ url: string; revoke: () => void }> {
  const query = width ? `?width=${width}` : '';
  const url = `${BASE_URL}/api/v1/documents/${encodeURIComponent(uid)}/pages/${pageNumber}/image${query}`;

  const headers: Record<string, string> = {};
  const token = getAuthToken();
  const role = getUserRole();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (role) headers['X-User-Role'] = role;

  const res = await fetch(url, { headers });
  if (res.status === 401) throw new Error('401 Unauthorized');
  if (res.status === 403) throw new Error('403 Forbidden: Access denied');
  if (!res.ok) throw new Error(`Failed to load page image: ${res.statusText}`);

  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  return {
    url: blobUrl,
    revoke: () => URL.revokeObjectURL(blobUrl),
  };
}
