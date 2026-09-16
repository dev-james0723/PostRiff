import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: 'alpha',
  plugins: [react()],
  base: '/',
  build: { outDir: '../dist-alpha', emptyOutDir: true, sourcemap: false },
});
