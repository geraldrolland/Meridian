import { Response } from 'express';
import redis from '../../config/redis';
import config from '../../config';
import { AuthenticatedRequest } from '../../types';
import { BaseOn, getIdentifier, setRateLimitHeaders } from './utils';

/**
 * Redis Lua script implementing an atomic token bucket rate limiter.
 *
 * The script:
 * 1. Reads current token count and last refill timestamp from a Redis hash
 * 2. Calculates tokens to add based on elapsed time × refill rate
 * 3. Caps tokens at bucket max capacity
 * 4. If tokens < 1, returns 0 (denied) with wait time in ms
 * 5. If tokens >= 1, decrements by 1 and returns 1 (allowed) with remaining tokens
 *
 * All operations are atomic — no race conditions under concurrent requests.
 */
const TOKEN_BUCKET_LUA = `
local key = KEYS[1]
local max = tonumber(ARGV[1])
local refillRate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'lastRefill')
local tokens = tonumber(data[1])
local lastRefill = tonumber(data[2])

if tokens == nil then
  tokens = max
  lastRefill = now
end

local elapsed = math.max(0, now - lastRefill)
tokens = math.min(max, tokens + elapsed * refillRate)

if tokens < 1 then
  local deficit = 1 - tokens
  local waitSec = deficit / refillRate
  redis.call('HMSET', key, 'tokens', tostring(tokens), 'lastRefill', tostring(now))
  redis.call('EXPIRE', key, math.ceil(waitSec) + 10)
  return {0, tostring(math.ceil(waitSec * 1000))}
end

tokens = tokens - 1
redis.call('HMSET', key, 'tokens', tostring(tokens), 'lastRefill', tostring(now))
redis.call('EXPIRE', key, math.ceil(max / refillRate) + 10)
return {1, tostring(math.floor(tokens))}
`;

/**
 * Token bucket rate limiter using an atomic Redis Lua script.
 *
 * Allows short bursts up to bucket capacity, then refills at a steady rate.
 * Best for APIs with bursty traffic patterns (e.g., video processing).
 *
 * Falls back to per-route config if defined, otherwise uses global defaults.
 *
 * @param req - The incoming request
 * @param res - Express response (429 if bucket is empty)
 * @param baseOn - Whether to key by `"userId"` or `"ip"`
 * @param routePrefix - The matched route prefix for config lookup
 * @returns `true` if request is allowed, `false` if rate limited
 */
export async function RateLimitByTokenBucket(
  req: AuthenticatedRequest,
  res: Response,
  baseOn: BaseOn,
  routePrefix: string
): Promise<boolean> {
  const routeConfig = config.routes.find((r) => r.prefix === routePrefix);
  const max = routeConfig?.rateLimit?.max ?? config.rateLimit.max;
  const refillRate = routeConfig?.rateLimit?.refillRate ?? 1;

  const identifier = getIdentifier(req, baseOn);
  const key = `ratelimit:bucket:${routePrefix}:${identifier}`;
  const now = Date.now() / 1000;

  const result = (await redis.eval(
    TOKEN_BUCKET_LUA,
    1,
    key,
    String(max),
    String(refillRate),
    String(now)
  )) as [number, string];

  const allowed = result[0] === 1;
  const value = parseInt(result[1], 10);

  if (allowed) {
    setRateLimitHeaders(res, max, value, 0);
    return true;
  }

  const retryAfterMs = value;
  res.setHeader('Retry-After', Math.ceil(retryAfterMs / 1000));
  res.setHeader('X-RateLimit-Limit', max);
  res.setHeader('X-RateLimit-Remaining', 0);
  res.status(429).json({ error: 'Too many requests, please try again later' });
  return false;
}
