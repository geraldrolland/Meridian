import { Request } from 'express';

/**
 * Rate limiting algorithm selection.
 * - `"fixedWindow"` — counts requests in a fixed time window
 * - `"tokenBucket"` — refills tokens at a steady rate, allows bursts
 */
export type RateLimitStrategy = 'fixedWindow' | 'tokenBucket';

/**
 * Configuration for a single upstream route.
 *
 * @property prefix - Path prefix that triggers this route (e.g. `/api/auth`)
 * @property target - Upstream service URL (e.g. `http://auth-service:4000`)
 * @property rewrite - If true, strips the prefix before forwarding (default: false)
 * @property auth - Whether to enforce JWT auth on this route (default: true)
 * @property rateLimit - Optional per-route rate limit overrides
 */
export interface RouteConfig {
  prefix: string;
  target: string;
  rewrite?: boolean;
  auth?: boolean;
  rateLimit?: {
    windowMs: number;
    max: number;
    strategy: RateLimitStrategy;
    refillRate?: number;
  };
}

/**
 * Full gateway configuration sourced from environment variables.
 *
 * @property port - HTTP server port
 * @property host - Bind address
 * @property cors - CORS configuration (origins, methods, headers, credentials)
 * @property auth - JWT secret and path exclusion list
 * @property rateLimit - Global rate limit defaults (window + max)
 * @property routes - Array of upstream route configurations
 * @property redis - Redis connection parameters (sessions + rate limit counters)
 * @property proxySecret - Shared HMAC secret for signing proxy requests
 */
export interface GatewayConfig {
  port: number;
  host: string;
  cors: {
    origin: string | string[];
    methods: string[];
    allowedHeaders: string[];
    credentials: boolean;
  };
  auth: {
    jwtSecret: string;
    excludePaths: string[];
  };
  rateLimit: {
    windowMs: number;
    max: number;
  };
  routes: RouteConfig[];
  redis: {
    host: string;
    port: number;
    password?: string;
    db: number;
  };
  proxySecret: string;
}

/**
 * Decoded JWT payload structure used for session-based authentication.
 * The `sessionId` links the token to a Redis session record.
 *
 * @property sessionId - UUID v4 identifying the active session
 */
export interface JwtPayload {
  sessionId: string;
}

/**
 * Session data stored in Redis as `session:<sessionId>`.
 *
 * @property userId - The user's primary key
 * @property role - User role for authorization (reserved for future use)
 * @property email - User's email address
 */
export interface SessionData {
  userId: string;
  role: string;
  email: string;
}

/**
 * Extended Express Request that carries authenticated session data.
 * Populated by the auth middleware after JWT verification and session lookup.
 *
 * @property user - Session data if the request is authenticated; undefined if path is excluded
 */
export interface AuthenticatedRequest extends Request {
  user?: SessionData;
}
