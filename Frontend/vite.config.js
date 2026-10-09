import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // "@/..." resolves to src/..., the alias the shadcn-style registry components expect.
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
});
