import { Request, Response, NextFunction } from 'express';
import { logger } from '../config';

/**
 * Global error handler middleware.
 * Catches any unhandled errors that propagate through the Express pipeline.
 * Logs the full error stack trace and returns a generic 500 response
 * to avoid leaking internal details to clients.
 *
 * @param err - The unhandled error thrown by a previous middleware or route handler
 * @param _req - The original request (unused)
 * @param res - Express response (500 with generic error message)
 * @param _next - Next function (unused, required by Express signature)
 */
export function errorHandler(err: Error, _req: Request, res: Response, _next: NextFunction): void {
  logger.error('Unhandled error', { message: err.message, stack: err.stack });
  res.status(500).json({ error: 'Internal server error' });
}
