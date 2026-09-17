import { Request, Response, NextFunction } from 'express';
import { logger } from '../config';

/**
 * Request logging middleware for the auth service.
 * Logs an "Incoming request" entry on arrival and a "Request completed"
 * entry when the response finishes, including status code and duration.
 *
 * @param req  - The incoming Express request
 * @param res  - Express response (listens for the `finish` event)
 * @param next - Called immediately to avoid blocking the request pipeline
 */
export function requestLogger(req: Request, res: Response, next: NextFunction): void {
  const start = Date.now();

  logger.info('Incoming request', {
    method: req.method,
    url: req.originalUrl,
    ip: req.ip,
    userAgent: req.get('user-agent'),
  });

  res.on('finish', () => {
    const duration = Date.now() - start;
    logger.info('Request completed', {
      method: req.method,
      url: req.originalUrl,
      status: res.statusCode,
      duration: `${duration}ms`,
      ip: req.ip,
      userAgent: req.get('user-agent'),
    });
  });

  next();
}
