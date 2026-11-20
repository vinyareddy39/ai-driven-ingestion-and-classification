import createClient from 'openapi-fetch';
import type { paths } from './schema';

// Base URL handling: normalize trailing slash
const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';
export const BASE_URL = rawBaseUrl.replace(/\/+$/, '');

const DEFAULT_LOCAL_TOKEN = '7v0xX3WljSa89vceTyNKmhDpPO4_NIJ63jIC3mkAKbo';
let authToken: string | null = DEFAULT_LOCAL_TOKEN;
let userRole: string | null = 'admin';

export function setAuthToken(token: string | null) {
  authToken = token || DEFAULT_LOCAL_TOKEN;
}

export function getAuthToken(): string | null {
  return authToken || DEFAULT_LOCAL_TOKEN;
}

export function setUserRole(role: string | null) {
  userRole = role || 'admin';
}

export function getUserRole(): string | null {
  return userRole || 'admin';
}

export const setActiveRole = setUserRole;
export const getActiveRole = getUserRole;
export { api } from '../services/api';

export const ReviewQueueItem = {};
export const IngestResponse = {};
export const DocumentSummaryItem = {};
export const ReviewActionRequest = {};
export const ReviewDetailResponse = {};
export const AdminConfigResponse = {};
export const AdminConfigUpdateRequest = {};
export const ClassThresholdConfig = {};
export const ConfigHistoryResponse = {};
export const ReprocessPreviewRequest = {};
export const ReprocessPreviewResponse = {};
export const ReprocessResponse = {};

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

// Attach Authorization and X-User-Role headers to all requests
client.use({
  async onRequest({ request }) {
    if (authToken) {
      request.headers.set('Authorization', `Bearer ${authToken}`);
    } else if (userRole) {
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

