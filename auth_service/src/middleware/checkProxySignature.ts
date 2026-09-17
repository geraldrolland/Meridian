import crypto from 'crypto';
import { Request, Response, NextFunction } from 'express';
import config from '../config';

/**
 * Middleware that verifies HMAC-SHA256 proxy signatures from the API gateway.
 *
 * Every request forwarded by the gateway includes two headers:
 * - `x-proxy-signature`: HMAC-SHA256 of `"{METHOD}:{URL}:{TIMESTAMP}"` using the shared secret
 * - `x-proxy-timestamp`: Unix epoch in milliseconds
 *
 * Verification steps:
 * 1. Check both headers are present
 * 2. Validate timestamp is a valid number
 * 3. Reject if timestamp is older than 30 seconds (replay protection)
 * 4. Recompute the HMAC and compare using `crypto.timingSafeEqual` (constant-time)
 *
 * @param req - Incoming request from the API gateway
 * @param res - Express response (403 on failure)
 * @param next - Called if signature is valid
 */
export function checkProxySignature(req: Request, res: Response, next: NextFunction): void {
  const signature = req.headers['x-proxy-signature'] as string | undefined;
  const timestamp = req.headers['x-proxy-timestamp'] as string | undefined;

  if (!signature || !timestamp) {
    res.status(403).json({ error: 'Missing proxy signature' });
    return;
  }

  const ts = parseInt(timestamp, 10);
  if (isNaN(ts)) {
    res.status(403).json({ error: 'Invalid proxy timestamp' });
    return;
  }

  const elapsed = Date.now() - ts;
  if (elapsed > 30000) {
    res.status(403).json({ error: 'Proxy signature expired' });
    return;
  }

  const payload = `${req.method}:${req.originalUrl}:${timestamp}`;
  const expected = crypto
    .createHmac('sha256', config.proxySecret)
    .update(payload)
    .digest('hex');

  if (!crypto.timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'))) {
    res.status(403).json({ error: 'Invalid proxy signature' });
    return;
  }

  next();
}
