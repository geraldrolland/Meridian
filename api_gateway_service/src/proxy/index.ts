import crypto from 'crypto';
import { Router, Request, Response } from 'express';
import { createProxyMiddleware, Options } from 'http-proxy-middleware';
import config from '../config';
import { logger } from '../middleware/logger';
import { AuthenticatedRequest } from '../types';

const router = Router();

/**
 * Sets up reverse proxy routes for all configured upstream services.
 *
 * For each route in `config.routes`, creates an `http-proxy-middleware`
 * instance that:
 * 1. Matches requests by path prefix (via `pathFilter`)
 * 2. Forwards to the target service with `changeOrigin: true`
 * 3. Signs each outgoing request with HMAC-SHA256 (`x-proxy-signature`)
 *    using the shared `PROXY_SECRET` for upstream verification
 * 4. Optionally rewrites the path (strips prefix) if `route.rewrite` is true
 *
 * The proxy middleware is mounted on the Express router WITHOUT Express-level
 * prefix stripping — the `pathFilter` handles matching while preserving the
 * full URL for the upstream service.
 */
function setupRoutes(): void {
  for (const route of config.routes) {
    const proxyOptions: Options = {
      target: route.target,
      changeOrigin: true,
      pathRewrite: route.rewrite
        ? { [`^${route.prefix}`]: '' }
        : undefined,
      on: {
        /**
         * Signs every outgoing proxy request with HMAC-SHA256.
         * Payload format: `"{METHOD}:{URL}:{TIMESTAMP}"`.
         * The upstream service verifies this using the shared PROXY_SECRET.
         */
        proxyReq: (proxyReq, req) => {
          const timestamp = Date.now().toString();
          const payload = `${req.method}:${req.url}:${timestamp}`;
          const signature = crypto
            .createHmac('sha256', config.proxySecret)
            .update(payload)
            .digest('hex');

          proxyReq.setHeader('x-proxy-signature', signature);
          proxyReq.setHeader('x-proxy-timestamp', timestamp);

          const authReq = req as AuthenticatedRequest;
          if (authReq.user) {
            const sessionValue = encodeURIComponent(JSON.stringify(authReq.user));
            const existingCookie = proxyReq.getHeader('cookie') || '';
            const cookie = existingCookie
              ? `${existingCookie}; session=${sessionValue}`
              : `session=${sessionValue}`;
            proxyReq.setHeader('cookie', cookie);
          }

          logger.info('Proxying request', {
            from: req.url,
            to: `${route.target}${req.url}`,
            prefix: route.prefix,
          });
        },
        /**
         * Handles proxy connection errors (upstream unreachable, timeout, etc.).
         * Returns 502 Bad Gateway with a generic error message.
         */
        error: (err, _req, res) => {
          logger.error('Proxy error', { error: err.message });
          (res as Response).status(502).json({ error: 'Bad gateway - upstream service unavailable' });
        },
      },
    };

    router.use(createProxyMiddleware({ ...proxyOptions, pathFilter: route.prefix }));
  }
}

if (config.routes.length > 0) {
  setupRoutes();
}

export default router;
