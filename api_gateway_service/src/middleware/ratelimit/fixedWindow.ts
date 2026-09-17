import { Response } from 'express';
import redis from '../../config/redis';
import config from '../../config';
import { AuthenticatedRequest } from '../../types';
import { BaseOn, getIdentifier, setRateLimitHeaders } from './utils';

/**
 * Fixed window rate limiter using Redis INCR + EXPIRE.
 *
 * Algorithm:
 * 1. Increment a counter key `ratelimit:fixed:<route>:<identifier>`
 * 2. On first request (count === 1), set TTL to the window duration
 * 3. If count exceeds max, return 429 with Retry-After header
 *
 * Falls back to per-route config if defined, otherwise uses global defaults.
 *
 * @param req - The incoming request
 * @param res - Express response (429 if rate limit exceeded)
 * @param baseOn - Whether to key by `"userId"` or `"ip"`
 * @param routePrefix - The matched route prefix for config lookup
 * @returns `true` if request is allowed, `false` if rate limited
 */
export async function RateLimitByFixedWindow(
  req: AuthenticatedRequest,
  res: Response,
  baseOn: BaseOn,
  routePrefix: string
): Promise<boolean> {
  const routeConfig = config.routes.find((r) => r.prefix === routePrefix);
  const windowMs = routeConfig?.rateLimit?.windowMs ?? config.rateLimit.windowMs;
  const max = routeConfig?.rateLimit?.max ?? config.rateLimit.max;

  const identifier = getIdentifier(req, baseOn);
  const windowSec = Math.ceil(windowMs / 1000);
  const key = `ratelimit:fixed:${routePrefix}:${identifier}`;

  const current = await redis.incr(key);
  if (current === 1) {
    await redis.expire(key, windowSec);
  }

  const ttl = await redis.ttl(key);
  const resetMs = Date.now() + ttl * 1000;
  const remaining = max - current;

  setRateLimitHeaders(res, max, remaining, resetMs);

  if (current > max) {
    res.setHeader('Retry-After', ttl);
    res.status(429).json({ error: 'Too many requests, please try again later' });
    return false;
  }

  return true;
}
