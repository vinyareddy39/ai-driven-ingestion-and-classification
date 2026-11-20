/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/tests/setup.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ingest': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/review': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/reprocess': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/metrics': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/audit': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
