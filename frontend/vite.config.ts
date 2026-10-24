import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api to the Python backend, so the UI is same-origin in dev and prod.
// Start the backend with the same PIXSIFT_TOKEN so the proxy can present the access cookie.
const token = process.env.PIXSIFT_TOKEN

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        headers: token ? { cookie: `pixsift_token=${token}` } : undefined,
      },
    },
  },
})
