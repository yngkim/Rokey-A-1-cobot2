import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiPort = process.env.VITE_API_PORT || '8080';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': `http://localhost:${apiPort}`,
    },
  },
});
