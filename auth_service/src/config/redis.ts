import Redis from 'ioredis';
import config from './index';

/**
 * Redis client for session storage and token management.
 * Sessions are stored as `session:<UUID>` with a 7-day TTL.
 * Uses exponential backoff retry strategy (50ms × attempt, max 2s).
 */
const redis = new Redis({
  host: config.redis.host,
  port: config.redis.port,
  password: config.redis.password,
  db: config.redis.db,
  maxRetriesPerRequest: 3,
  retryStrategy(times) {
    const delay = Math.min(times * 50, 2000);
    return delay;
  },
});

/**
 * Logs Redis connection errors to prevent silent failures.
 */
redis.on('error', (err) => {
  console.error('[Redis] Connection error:', err.message);
});

/**
 * Logs successful Redis connections.
 */
redis.on('connect', () => {
  console.log('[Redis] Connected');
});

export default redis;
