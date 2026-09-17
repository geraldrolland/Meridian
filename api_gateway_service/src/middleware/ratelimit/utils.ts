import { Response } from 'express';
import { AuthenticatedRequest } from '../../types';

export type BaseOn = 'ip' | 'userId';

/**
 * Extracts the rate limit identifier from the request.
 * If the user is authenticated (has a userId), rates are keyed by userId.
 * Otherwise, rates are keyed by the client's IP address.
 *
 * @param req - The incoming request with optional session data
 * @param baseOn - Whether to key by `"userId"` or `"ip"`
 * @returns The rate limit key identifier
 */
export function getIdentifier(req: AuthenticatedRequest, baseOn: BaseOn): string {
  if (baseOn === 'userId' && req.user?.userId) {
    return req.user.userId;
  }
  return req.ip || req.socket.remoteAddress || 'unknown';
}

/**
 * Sets standard rate limit response headers.
 *
 * @param res - Express response to set headers on
 * @param limit - Maximum allowed requests in the window
 * @param remaining - Remaining requests in the current window
 * @param resetMs - Unix timestamp (ms) when the window resets
 */
export function setRateLimitHeaders(
  res: Response,
  limit: number,
  remaining: number,
  resetMs: number
): void {
  res.setHeader('X-RateLimit-Limit', limit);
  res.setHeader('X-RateLimit-Remaining', Math.max(0, remaining));
  res.setHeader('X-RateLimit-Reset', Math.ceil(resetMs / 1000));
}
