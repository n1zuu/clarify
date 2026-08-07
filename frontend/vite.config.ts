import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';
import { defineConfig, type UserConfig } from 'vite';

export default defineConfig((): UserConfig => {
  // Load certs if they exist — needed for HTTPS dev server over Tailscale
  const certPath = path.join(__dirname, 'cert.pem');
  const keyPath  = path.join(__dirname, 'key.pem');
  const hasCerts = fs.existsSync(certPath) && fs.existsSync(keyPath);

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      hmr: process.env.DISABLE_HMR !== 'true'
        ? {
            // Use wss:// for HMR so browsers don't block it on HTTPS pages
            protocol: hasCerts ? 'wss' : 'ws',
            port: 3000,
          }
        : false,
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      allowedHosts: true,
      cors: true,
      // Run Vite itself over HTTPS so module requests aren't treated as mixed content
      https: hasCerts
        ? {
            cert: fs.readFileSync(certPath),
            key:  fs.readFileSync(keyPath),
          }
        : undefined,
    },
  };
});