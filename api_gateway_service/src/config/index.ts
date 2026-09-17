import dotenv from 'dotenv';
import { GatewayConfig, RouteConfig } from '../types';

dotenv.config();

/**
 * Parses the `ROUTES` environment variable into an array of route configs.
 * Expects a JSON string like `[{"prefix":"/api/auth","target":"http://auth-service:4000"}]`.
 * Returns an empty array on parse failure with a console error.
 *
 * @returns Parsed route configurations
 */
function parseRoutes(): RouteConfig[] {
  const routesJson = process.env.ROUTES || '[]';
  try {
    return JSON.parse(routesJson) as RouteConfig[];
  } catch {
    console.error('Failed to parse ROUTES env variable. Using empty routes.');
    return [];
  }
}

/**
 * Parses the `CORS_ORIGIN` environment variable into an array of allowed origins.
 * Returns `['*']` if set to `*` (default), otherwise splits by comma.
 *
 * @returns Array of allowed CORS origins
 */
function parseCorsOrigins(): string[] {
  const origins = process.env.CORS_ORIGIN || '*';
  if (origins === '*') return ['*'];
  return origins.split(',').map((o) => o.trim());
}

/**
 * Centralized gateway configuration sourced from environment variables.
 * All values have sensible defaults for local development.
 */
const config: GatewayConfig = {
  port: parseInt(process.env.PORT || '3000', 10),
  host: process.env.HOST || '127.0.0.1',
  cors: {
    origin: parseCorsOrigins(),
    methods: (process.env.CORS_METHODS || 'GET,POST,PUT,PATCH,DELETE,OPTIONS').split(','),
    allowedHeaders: (process.env.CORS_HEADERS || 'Content-Type,Authorization,X-Request-ID').split(','),
    credentials: process.env.CORS_CREDENTIALS === 'true',
  },
  auth: {
    jwtSecret: process.env.JWT_SECRET || 'change-me-in-production',
    excludePaths: (process.env.AUTH_EXCLUDE_PATHS || '/health,/api/auth/login,/api/auth/register').split(','),
  },
  rateLimit: {
    windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS || '900000', 10),
    max: parseInt(process.env.RATE_LIMIT_MAX || '100', 10),
  },
  routes: parseRoutes(),
  redis: {
    host: process.env.REDIS_HOST || '127.0.0.1',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
    password: process.env.REDIS_PASSWORD || undefined,
    db: parseInt(process.env.REDIS_DB || '0', 10),
  },
  proxySecret: process.env.PROXY_SECRET || 'change-me-in-production',
};

export default config;
