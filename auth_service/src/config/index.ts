import dotenv from 'dotenv';
import winston from 'winston';

dotenv.config();

/**
 * Structured JSON logger for the auth service.
 * Outputs to stdout with ISO timestamps and error stack traces.
 * Log level is configurable via `LOG_LEVEL` env var (default: "info").
 */
export const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.errors({ stack: true }),
    winston.format.json()
  ),
  defaultMeta: { service: 'auth-service' },
  transports: [new winston.transports.Console()],
});

/**
 * Centralized configuration object sourced from environment variables.
 * All values have sensible defaults for local development.
 *
 * @property port - HTTP server port (default: 4000)
 * @property host - Bind address (default: 127.0.0.1)
 * @property db - PostgreSQL connection parameters
 * @property redis - Redis connection parameters
 * @property jwt - JWT signing secrets and token expiry durations
 * @property proxySecret - Shared HMAC-SHA256 secret for API gateway proxy signature verification
 * @property logLevel - Winston log level
 */
const config = {
  port: parseInt(process.env.PORT || '4000', 10),
  host: process.env.HOST || '127.0.0.1',
  db: {
    host: process.env.DB_HOST || '127.0.0.1',
    port: parseInt(process.env.DB_PORT || '5432', 10),
    user: process.env.DB_USER || 'postgres',
    password: process.env.DB_PASSWORD || 'postgres',
    database: process.env.DB_NAME || 'auth_db',
  },
  redis: {
    host: process.env.REDIS_HOST || '127.0.0.1',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
    password: process.env.REDIS_PASSWORD || undefined,
    db: parseInt(process.env.REDIS_DB || '0', 10),
  },
  jwt: {
    secret: process.env.JWT_SECRET || 'change-me-in-production',
    accessTokenExpiry: process.env.ACCESS_TOKEN_EXPIRY || '7m',
    refreshTokenExpiry: process.env.REFRESH_TOKEN_EXPIRY || '7d',
    refreshTokenMaxAge: parseInt(process.env.REFRESH_TOKEN_MAX_AGE || '604800000', 10),
  },
  proxySecret: process.env.PROXY_SECRET || 'change-me-in-production',
  logLevel: process.env.LOG_LEVEL || 'info',
};

export default config;
