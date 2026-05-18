import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react-swc';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiPort = env.VITE_API_PORT || '8001';
  const apiHost = env.VITE_API_HOST || 'localhost';

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        '/api': `http://${apiHost}:${apiPort}`,
      },
    },
  };
});

