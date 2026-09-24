import crypto from 'crypto';
import { Router, Request, Response, NextFunction } from 'express';
import { createProxyMiddleware, Options } from 'http-proxy-middleware';
import config from '../config';
import { logger } from '../middleware/logger';
import { AuthenticatedRequest } from '../types';

const router = Router();

/**
 * Signs the incoming request with HMAC-SHA256 before proxying.
 *
 * http-proxy-middleware v4 / httpxy does not reliably fire `on.proxyReq`
 * before headers are finalized, so signatures are attached on the Express
 * request. httpxy copies `req.headers` onto the upstream ClientRequest.
 *
 * Payload format: `"{METHOD}:{URL}:{TIMESTAMP}"` — verified by upstream
 * services via `checkProxySignature` using the shared `PROXY_SECRET`.
 */
export function signProxyRequest(req: Request, _res: Response, next: NextFunction): void {
  const timestamp = Date.now().toString();
  const url = req.originalUrl || req.url;
  const payload = `${req.method}:${url}:${timestamp}`;
  const signature = crypto
    .createHmac('sha256', config.proxySecret)
    .update(payload)
    .digest('hex');

  req.headers['x-proxy-signature'] = signature;
  req.headers['x-proxy-timestamp'] = timestamp;

  next();
}

router.use(signProxyRequest);

/**
 * Sets up reverse proxy routes for all configured upstream services.
 *
 * For each route in `config.routes`, creates an `http-proxy-middleware`
 * instance that:
 * 1. Matches requests by path prefix (via `pathFilter`)
 * 2. Forwards to the target service with `changeOrigin: true`
 * 3. Relies on `signProxyRequest` for HMAC-SHA256 (`x-proxy-signature`)
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
         * Re-applies session cookie when the gateway authenticated the user.
         * Signature headers are already set by `signProxyRequest`.
         */
        proxyReq: (proxyReq, req) => {
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
