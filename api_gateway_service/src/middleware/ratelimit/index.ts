import { Response, NextFunction } from 'express';
import { AuthenticatedRequest, RateLimitStrategy } from '../../types';
import { RateLimitByFixedWindow } from './fixedWindow';
import { RateLimitByTokenBucket } from './tokenBucket';

type RateLimitFunction = (
  req: AuthenticatedRequest,
  res: Response,
  baseOn: 'ip' | 'userId',
  routePrefix: string
) => Promise<boolean>;

/** Maps strategy names to their implementation functions. */
const strategyMap: Record<RateLimitStrategy, RateLimitFunction> = {
  fixedWindow: RateLimitByFixedWindow,
  tokenBucket: RateLimitByTokenBucket,
};

/**
 * Route-to-strategy mapping.
 * `/api/video` uses token bucket (bursty traffic); all others use fixed window.
 * Add new route-specific strategies here as needed.
 */
const routeHandlers: Record<string, RateLimitFunction> = {
  '/api/video': RateLimitByTokenBucket,
  '*': RateLimitByFixedWindow,
};

/**
 * Matches a request path to the most specific rate limit strategy.
 * Uses longest-prefix matching — `/api/video/upload` matches `/api/video`.
 *
 * @param path - The request path to match
 * @returns The matched handler function and its route prefix
 */
function matchRoute(path: string): { handler: RateLimitFunction; prefix: string } {
  let bestMatch = '';
  let bestHandler = routeHandlers['*'];

  for (const prefix of Object.keys(routeHandlers)) {
    if (prefix === '*') continue;
    if (path.startsWith(prefix) && prefix.length > bestMatch.length) {
      bestMatch = prefix;
      bestHandler = routeHandlers[prefix];
    }
  }

  if (bestMatch) {
    return { handler: bestHandler, prefix: bestMatch };
  }

  return { handler: bestHandler, prefix: '*' };
}

/**
 * Rate limiting middleware entry point.
 * Selects the appropriate strategy based on the request path,
 * determines the rate limit key (userId or IP), and enforces the limit.
 *
 * @param req - The incoming request with optional session data
 * @param res - Express response (429 if rate limited)
 * @param next - Called if the request is within rate limits
 */
export async function rateLimiter(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  const { handler, prefix } = matchRoute(req.path);

  const baseOn: 'ip' | 'userId' = req.user?.userId ? 'userId' : 'ip';

  try {
    const allowed = await handler(req, res, baseOn, prefix);
    if (allowed) {
      next();
    }
  } catch {
    next();
  }
}
