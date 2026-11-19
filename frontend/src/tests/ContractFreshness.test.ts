import { describe, it, expect } from 'vitest';
import fs from 'fs';
import path from 'path';

describe('API Contract Freshness (Requirement 24)', () => {
  it('fails if generated schema.d.ts is missing or out of date with openapi.json', () => {
    const openapiPath = path.resolve(__dirname, '../../../openapi.json');
    const schemaPath = path.resolve(__dirname, '../api/schema.d.ts');

    expect(fs.existsSync(openapiPath), 'openapi.json must exist in project root').toBe(true);
    expect(fs.existsSync(schemaPath), 'schema.d.ts must exist in src/api/').toBe(true);

    const openapiRaw = fs.readFileSync(openapiPath, 'utf-8');
    const schemaRaw = fs.readFileSync(schemaPath, 'utf-8');

    const openapi = JSON.parse(openapiRaw);
    const paths = Object.keys(openapi.paths || {});

    // Ensure all endpoints in openapi.json are represented in generated TypeScript schema
    for (const p of paths) {
      expect(
        schemaRaw.includes(p),
        `Generated TypeScript client is missing path: ${p}. Run 'npm run api:gen' to refresh.`
      ).toBe(true);
    }

    // Verify key schema components
    const requiredSchemas = [
      'SystemInfoResponse',
      'ReviewQueueResponse',
      'ReviewDetailResponse',
      'DocumentComplianceDetailResponse',
      'DashboardMetricsResponse',
      'AdminConfigResponse',
    ];

    for (const s of requiredSchemas) {
      expect(
        schemaRaw.includes(s),
        `Generated schema is missing schema component: ${s}. Run 'npm run api:gen'.`
      ).toBe(true);
    }
  });
});
