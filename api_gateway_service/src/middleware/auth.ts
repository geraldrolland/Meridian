import { Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import config from '../config';
import redis from '../config/redis';
import { AuthenticatedRequest, JwtPayload, SessionData } from '../types';

/**
 * JWT authentication middleware for the API gateway.
 *
 * Flow:
 * 1. Check if the request path is in `AUTH_EXCLUDE_PATHS` — if so, skip auth
 * 2. Extract the Bearer token from the Authorization header
 * 3. Verify the JWT signature using `JWT_SECRET`
 * 4. Extract `sessionId` from the decoded payload
 * 5. Look up the session in Redis (`session:<sessionId>`)
 * 6. Attach the session data (`userId`, `role`, `email`) to `req.user`
 *
 * Paths like `/health`, `/api/auth/login`, and `/api/auth/register` are
 * excluded from authentication to allow unauthenticated access.
 *
 * @param req - The incoming request (extended with optional `user` property)
 * @param res - Express response (401 on auth failure)
 * @param next - Called with populated `req.user` if authentication succeeds
 */
export async function authMiddleware(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  const path = req.path;

  const isExcluded = config.auth.excludePaths.some((excluded) => path.startsWith(excluded));
  if (isExcluded) {
    return next();
  }

  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Missing or invalid Authorization header' });
    return;
  }

  const token = authHeader.split(' ')[1];

  try {
    const decoded = jwt.verify(token, config.auth.jwtSecret) as JwtPayload;

    if (!decoded.sessionId) {
      res.status(401).json({ error: 'Invalid token payload' });
      return;
    }

    const sessionRaw = await redis.get(`session:${decoded.sessionId}`);
    if (!sessionRaw) {
      res.status(401).json({ error: 'Session expired or not found' });
      return;
    }

    const session: SessionData = JSON.parse(sessionRaw);
    req.user = session;
    next();
  } catch (err) {
    if (err instanceof jwt.JsonWebTokenError) {
      res.status(401).json({ error: 'Invalid or expired token' });
      return;
    }
    res.status(500).json({ error: 'Authentication service unavailable' });
  }
}
