/**
 * connection_check.mjs
 * Calls every /api/v1/ endpoint in order using openapi-fetch (from frontend/node_modules).
 * Validates required fields per response. Prints PASS/FAIL per endpoint.
 *
 * Run:  node scripts/connection_check.mjs
 * Label: LOCAL MODE  (X-User-Role: admin, no real token)
 */

import { pathToFileURL } from 'url';
import { resolve } from 'path';

// Resolve openapi-fetch from the frontend tree (absolute file URL for ESM)
const fetchPkg = pathToFileURL(
  resolve('frontend/node_modules/openapi-fetch/dist/index.mjs')
).href;

const { default: createClient } = await import(fetchPkg);

// ── Config ────────────────────────────────────────────────────────────────────
const BASE_URL   = 'http://127.0.0.1:8000';
const ROLE       = 'admin';
const SAMPLE_UID = '21c9c7dd-cf95-4ecb-b20b-686a3923c228'; // clean_invoice.pdf
const DUP_UID    = '8a9cecdf-c8b0-4c2c-9dd4-f1dbec26d496'; // duplicate

// ── Client setup ──────────────────────────────────────────────────────────────
const client = createClient({ baseUrl: BASE_URL });

client.use({
  onRequest({ request }) {
    request.headers.set('X-User-Role', ROLE);
    return request;
  },
});

// ── Helpers ───────────────────────────────────────────────────────────────────
let pass = 0, fail = 0;

function shapeOk(data, keys) {
  if (!keys.length) return true;
  if (!data || typeof data !== 'object') return false;
  const target = Array.isArray(data) ? (data[0] ?? {}) : data;
  const missing = keys.filter(k => !(k in target));
  if (missing.length) {
    console.log(`    ⚠ SHAPE MISMATCH — missing: ${missing.join(', ')}`);
    return false;
  }
  return true;
}

async function check(label, fn, requiredKeys = []) {
  console.log(`\n[${label}]`);
  try {
    const result = await fn();
    const { data, error, response } = result;
    const status = response?.status ?? '???';
    const is2xx  = status >= 200 && status < 300;

    console.log(`  STATUS : ${status}`);

    if (error || !is2xx) {
      console.log(`  RESULT : FAIL — ${JSON.stringify(error ?? 'non-2xx')}`);
      fail++;
      return null;
    }

    const ok = shapeOk(data, requiredKeys);
    console.log(`  SHAPE  : ${ok ? 'OK' : 'FAIL'}`);
    console.log(`  BODY   : ${JSON.stringify(data).slice(0, 220)}…`);
    console.log(`  RESULT : ${ok ? 'PASS' : 'FAIL'}`);
    ok ? pass++ : fail++;
    return data;
  } catch (e) {
    console.log(`  STATUS : EXCEPTION`);
    console.log(`  RESULT : FAIL — ${e.message}`);
    fail++;
    return null;
  }
}

// ── Calls ─────────────────────────────────────────────────────────────────────
console.log('='.repeat(62));
console.log('connection_check.mjs  ·  LOCAL MODE');
console.log(`BASE   : ${BASE_URL}`);
console.log(`ROLE   : ${ROLE}`);
console.log(`UID    : ${SAMPLE_UID}`);
console.log('='.repeat(62));

// 1. system/info  — actual keys: mode, version, environment, max_upload_size_bytes, allowed_file_types
await check('GET /api/v1/system/info',
  () => client.GET('/api/v1/system/info'),
  ['mode', 'version', 'max_upload_size_bytes', 'allowed_file_types']);

// 2. auth/me  — actual keys: id, username, role, permissions
await check('GET /api/v1/auth/me',
  () => client.GET('/api/v1/auth/me'),
  ['id', 'username', 'role', 'permissions']);

// 3. review/queue  — array; item keys: task_id, document_uid, status
await check('GET /api/v1/review/queue',
  () => client.GET('/api/v1/review/queue'),
  ['task_id', 'document_uid', 'status']);

// 4. documents list  — actual keys: total, items, limit, offset
await check('GET /api/v1/documents',
  () => client.GET('/api/v1/documents', { params: { query: { page: 1, page_size: 5 } } }),
  ['total', 'items', 'limit', 'offset']);

// 5. document detail  — actual keys: uid, sha256, file_name, predictedType, reviewStatus
await check('GET /api/v1/documents/{uid}',
  () => client.GET('/api/v1/documents/{uid}', { params: { path: { uid: SAMPLE_UID } } }),
  ['uid', 'file_name', 'predictedType', 'reviewStatus']);

// 6. audit  — same shape as detail
await check('GET /api/v1/audit/{uid}',
  () => client.GET('/api/v1/audit/{uid}', { params: { path: { uid: SAMPLE_UID } } }),
  ['uid', 'file_name']);

// 7. reprocess preview (dry run)  — actual keys: matched_count, queued_count, dry_run, job_id
await check('POST /api/v1/reprocess/preview',
  () => client.POST('/api/v1/reprocess/preview', {
    body: { uid: SAMPLE_UID, dry_run: true }
  }),
  ['matched_count', 'dry_run', 'job_id']);

// 8. dashboard/metrics  — actual keys: total_documents, pending_review, auto_accepted
await check('GET /api/v1/dashboard/metrics',
  () => client.GET('/api/v1/dashboard/metrics'),
  ['total_documents', 'pending_review', 'auto_accepted']);

// 9. admin/config  — actual keys: pipeline, classes
await check('GET /api/v1/admin/config',
  () => client.GET('/api/v1/admin/config'),
  ['pipeline']);

// 10. admin/config/history  — array; item keys: revision, changed_at, changed_by
await check('GET /api/v1/admin/config/history',
  () => client.GET('/api/v1/admin/config/history'),
  ['revision', 'changed_at', 'changed_by']);

// ── Summary ───────────────────────────────────────────────────────────────────
console.log('\n' + '='.repeat(62));
console.log(`TOTAL ${pass + fail}  |  PASS ${pass}  |  FAIL ${fail}`);
console.log('='.repeat(62));
if (fail > 0) process.exit(1);
