import { Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import crypto from 'crypto';
import config from '../config';
import redis from '../config/redis';
import { JwtPayload, SessionData } from '../types';
import { logger } from '../middleware/logger';

/**
 * Token refresh handler (gateway-side implementation).
 *
 * Reads the refresh token from the `refresh` httpOnly cookie, verifies it,
 * rotates the session (deletes old, creates new), and issues a fresh
 * access + refresh token pair.
 *
 * This is the gateway's own refresh handler — the auth service has an
 * identical implementation for direct access.
 *
 * @param req.cookies.refresh - The current refresh token (httpOnly cookie)
 * @returns 200 with `{ accessToken }` and new refresh cookie
 * @returns 401 if refresh token is missing, invalid, or session has expired
 * @returns 500 on unexpected errors
 */
export async function refreshTokenHandler(req: Request, res: Response): Promise<void> {
  const refreshToken = req.cookies?.refresh;

  if (!refreshToken) {
    res.status(401).json({ error: 'Missing refresh token' });
    return;
  }

  try {
    const decoded = jwt.verify(refreshToken, config.auth.jwtSecret) as JwtPayload;

    if (!decoded.sessionId) {
      res.status(401).json({ error: 'Invalid refresh token payload' });
      return;
    }

    const sessionRaw = await redis.get(`session:${decoded.sessionId}`);
    if (!sessionRaw) {
      res.status(401).json({ error: 'Session expired or not found' });
      return;
    }

    const session: SessionData = JSON.parse(sessionRaw);

    await redis.del(`session:${decoded.sessionId}`);

    const newSessionId = crypto.randomUUID();

    await redis.set(`session:${newSessionId}`, JSON.stringify(session), 'EX', 604800);

    const accessToken = jwt.sign(
      { sessionId: newSessionId },
      config.auth.jwtSecret,
      { expiresIn: process.env.ACCESS_TOKEN_EXPIRY || '7m' } as jwt.SignOptions
    );

    const newRefreshToken = jwt.sign(
      { sessionId: newSessionId },
      config.auth.jwtSecret,
      { expiresIn: process.env.REFRESH_TOKEN_EXPIRY || '7d' } as jwt.SignOptions
    );

    res.cookie('refresh', newRefreshToken, {
      httpOnly: true,
      secure: true,
      sameSite: 'strict',
      path: '/api/auth/refresh-token',
      maxAge: parseInt(process.env.REFRESH_TOKEN_MAX_AGE || '604800000', 10),
    });

    logger.info('Token refreshed', { newSessionId });

    res.json({ accessToken });
  } catch (err) {
    if (err instanceof jwt.JsonWebTokenError) {
      res.status(401).json({ error: 'Invalid or expired refresh token' });
      return;
    }
    logger.error('Refresh token error', { error: (err as Error).message });
    res.status(500).json({ error: 'Token refresh failed' });
  }
}
