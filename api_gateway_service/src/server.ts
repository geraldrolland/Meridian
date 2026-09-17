import express from 'express';
import helmet from 'helmet';
import cookieParser from 'cookie-parser';
import config from './config';
import corsMiddleware from './middleware/cors';
import { authMiddleware } from './middleware/auth';
import { rateLimiter } from './middleware/ratelimit';
import { requestLogger, logger } from './middleware/logger';
import { errorHandler } from './middleware/errorHandler';
import proxyRouter from './proxy';

const app = express();

app.use(helmet());
app.use(corsMiddleware);
app.use(requestLogger);
app.use(cookieParser());

/**
 * GET /health — Health check endpoint.
 * Returns service status and current timestamp.
 * Excluded from auth middleware via AUTH_EXCLUDE_PATHS.
 */
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

/**
 * Middleware pipeline order is critical:
 * 1. authMiddleware — validates JWT tokens (skips excluded paths)
 * 2. rateLimiter — enforces per-route rate limits
 * 3. proxyRouter — forwards requests to upstream services
 * 4. express.json() — parses request bodies (AFTER proxy to avoid consuming streams)
 *
 * The proxy MUST come before express.json() because http-proxy-middleware
 * needs the raw request stream to forward to upstream services. If
 * express.json() runs first, it consumes the body and the proxy hangs.
 */
app.use(authMiddleware);
app.use(rateLimiter);
app.use(proxyRouter);

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

/**
 * 404 fallback — catches any request that doesn't match a defined route.
 */
app.use((_req, res) => {
  res.status(404).json({ error: 'Route not found' });
});

app.use(errorHandler);

/**
 * Starts the HTTP server.
 * Logs the bound address and registered route prefixes on startup.
 */
app.listen(config.port, config.host, () => {
  logger.info(`API Gateway running on ${config.host}:${config.port}`);
  logger.info(`Registered routes: ${config.routes.map((r) => r.prefix).join(', ') || 'none'}`);
});

export default app;
