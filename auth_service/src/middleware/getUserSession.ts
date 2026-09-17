import { Response, NextFunction } from 'express';
import { AuthenticatedRequest, SessionData } from '../types';

/**
 * Middleware that extracts session data from the `session` cookie
 * set by the API gateway proxy and attaches it to `req.user`.
 *
 * The gateway serializes `SessionData` as URI-encoded JSON in a
 * `session` cookie on every proxied request.
 *
 * @param req - Express request with cookies parsed by cookie-parser
 * @param res - Express response (401 if cookie is missing or invalid)
 * @param next - Called with populated `req.user` on success
 */
export async function getUserSession(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  const sessionCookie = req.cookies?.session;
  if (!sessionCookie) return next();

  try {
    const session: SessionData = JSON.parse(decodeURIComponent(sessionCookie));
    req.user = session;
    next();
  } catch {
    res.status(401).json({ error: 'Invalid session cookie' });
  }
}
