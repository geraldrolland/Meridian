import express, { Request, Response } from 'express';
import bcrypt from 'bcrypt';
import jwt from 'jsonwebtoken';
import crypto from 'crypto';
import config, { logger } from '../config';
import db from '../config/database';
import redis from '../config/redis';
import { JwtPayload, SessionData, AuthenticatedRequest } from '../types';
import { getUserSession } from '../middleware/getUserSession';

const router = express.Router();

/**
 * POST /api/auth/register
 *
 * Creates a new user account. Does NOT issue tokens — the user must
 * log in separately after registration.
 *
 * Validation:
 * - `email` and `password` are required
 * - `email` must contain "@"
 * - `password` must be at least 6 characters
 * - `email` must be unique (returns 409 on conflict)
 *
 * Passwords are hashed with bcrypt (12 salt rounds) before storage.
 *
 * @param req.body.email - User's email address
 * @param req.body.password - Plaintext password (hashed before DB insert)
 * @returns 201 with `{ user: { id, email } }`
 * @returns 400 on validation failure
 * @returns 409 if email is already registered
 * @returns 500 on database or hashing errors
 */
router.post('/register', async (req: Request, res: Response): Promise<void> => {
  const { email, password } = req.body;

  if (!email || !password) {
    res.status(400).json({ error: 'Email and password are required' });
    return;
  }

  if (typeof email !== 'string' || !email.includes('@')) {
    res.status(400).json({ error: 'Invalid email format' });
    return;
  }

  if (typeof password !== 'string' || password.length < 6) {
    res.status(400).json({ error: 'Password must be at least 6 characters' });
    return;
  }

  try {
    const existing = await db.query('SELECT id FROM users WHERE email = $1', [email]);
    if (existing.rows.length > 0) {
      res.status(409).json({ error: 'Email already registered' });
      return;
    }

    const saltRounds = 12;
    const hashPassword = await bcrypt.hash(password, saltRounds);

    const result = await db.query(
      'INSERT INTO users (email, hash_password) VALUES ($1, $2) RETURNING id, email, created_at',
      [email, hashPassword]
    );

    const user = result.rows[0];
    logger.info('User registered', { userId: user.id, email });

    res.status(201).json({
      user: { id: user.id, email: user.email },
    });
  } catch (err) {
    logger.error('Register error', { error: (err as Error).message });
    res.status(500).json({ error: 'Registration failed' });
  }
});

/**
 * POST /api/auth/login
 *
 * Authenticates a user and issues JWT access + refresh tokens.
 * The access token is returned in the response body.
 * The refresh token is set as an httpOnly cookie scoped to
 * `/api/auth/refresh-token` with a 7-day max age.
 *
 * A Redis session (`session:<UUID>`) is created with 7-day TTL
 * containing `{ userId, email }`.
 *
 * Uses constant-time bcrypt.compare to prevent timing attacks on
 * password verification.
 *
 * @param req.body.email - User's email address
 * @param req.body.password - Plaintext password
 * @returns 200 with `{ user: { id, email }, accessToken }` and refresh cookie
 * @returns 400 if email or password is missing
 * @returns 401 if credentials are invalid
 * @returns 500 on database or token errors
 */
router.post('/login', async (req: Request, res: Response): Promise<void> => {
  const { email, password } = req.body;

  if (!email || !password) {
    res.status(400).json({ error: 'Email and password are required' });
    return;
  }

  try {
    const result = await db.query('SELECT id, email, hash_password FROM users WHERE email = $1', [email]);
    if (result.rows.length === 0) {
      res.status(401).json({ error: 'Invalid credentials' });
      return;
    }

    const user = result.rows[0];
    const valid = await bcrypt.compare(password, user.hash_password);
    if (!valid) {
      res.status(401).json({ error: 'Invalid credentials' });
      return;
    }

    const sessionId = crypto.randomUUID();
    const sessionData: SessionData = { userId: user.id, email: user.email };
    await redis.set(`session:${sessionId}`, JSON.stringify(sessionData), 'EX', 604800);

    const accessToken = jwt.sign(
      { sessionId },
      config.jwt.secret,
      { expiresIn: config.jwt.accessTokenExpiry } as jwt.SignOptions
    );

    const refreshToken = jwt.sign(
      { sessionId },
      config.jwt.secret,
      { expiresIn: config.jwt.refreshTokenExpiry } as jwt.SignOptions
    );

    res.cookie('refresh', refreshToken, {
      httpOnly: true,
      secure: true,
      sameSite: 'strict',
      path: '/api/auth/refresh-token',
      maxAge: config.jwt.refreshTokenMaxAge,
    });

    logger.info('User logged in', { userId: user.id, email });

    res.json({
      user: { id: user.id, email: user.email },
      accessToken,
    });
  } catch (err) {
    logger.error('Login error', { error: (err as Error).message });
    res.status(500).json({ error: 'Login failed' });
  }
});

/**
 * POST /api/auth/logout
 *
 * Invalidates the current session by deleting it from Redis and
 * clearing the refresh token cookie.
 *
 * Requires a valid Bearer token in the Authorization header.
 * The session ID is extracted from the JWT to delete the Redis record.
 *
 * @param req.headers.authorization - "Bearer <accessToken>"
 * @returns 200 with `{ message: "Logged out successfully" }`
 * @returns 401 if token is missing or invalid
 * @returns 500 on unexpected errors
 */
router.post('/logout', async (req: Request, res: Response): Promise<void> => {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Missing or invalid Authorization header' });
    return;
  }

  const token = authHeader.split(' ')[1];

  try {
    const decoded = jwt.verify(token, config.jwt.secret) as JwtPayload;
    if (decoded.sessionId) {
      await redis.del(`session:${decoded.sessionId}`);
    }

    res.clearCookie('refresh', { path: '/api/auth/refresh-token' });
    logger.info('User logged out', { sessionId: decoded.sessionId });
    res.json({ message: 'Logged out successfully' });
  } catch (err) {
    if (err instanceof jwt.JsonWebTokenError) {
      res.status(401).json({ error: 'Invalid token' });
      return;
    }
    logger.error('Logout error', { error: (err as Error).message });
    res.status(500).json({ error: 'Logout failed' });
  }
});

/**
 * GET /api/auth/me
 *
 * Returns the authenticated user's profile (id and email).
 * Session data is extracted from the `session` cookie by the
 * getUserSession middleware.
 *
 * @returns 200 with `{ user: { id, email } }`
 * @returns 401 if session cookie is missing or invalid
 */
router.get('/me', getUserSession, (req: AuthenticatedRequest, res: Response): void => {
  res.json({ user: { id: req.user!.userId, email: req.user!.email } });
});

/**
 * POST /api/auth/refresh-token
 *
 * Rotates the refresh token by issuing a new session and token pair.
 * The old session is deleted from Redis and a new one is created with
 * a fresh UUID. This is token rotation — each refresh token is single-use.
 *
 * The refresh token is read from the `refresh` httpOnly cookie.
 * A new access token is returned in the response body and a new
 * refresh token is set as a cookie.
 *
 * @param req.cookies.refresh - The current refresh token (httpOnly cookie)
 * @returns 200 with `{ accessToken }` and new refresh cookie
 * @returns 401 if refresh token is missing, invalid, or session has expired
 * @returns 500 on unexpected errors
 */
router.post('/refresh-token', async (req: Request, res: Response): Promise<void> => {
  const refreshToken = req.cookies?.refresh;

  if (!refreshToken) {
    res.status(401).json({ error: 'Missing refresh token' });
    return;
  }

  try {
    const decoded = jwt.verify(refreshToken, config.jwt.secret) as JwtPayload;

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
      config.jwt.secret,
      { expiresIn: config.jwt.accessTokenExpiry } as jwt.SignOptions
    );

    const newRefreshToken = jwt.sign(
      { sessionId: newSessionId },
      config.jwt.secret,
      { expiresIn: config.jwt.refreshTokenExpiry } as jwt.SignOptions
    );

    res.cookie('refresh', newRefreshToken, {
      httpOnly: true,
      secure: true,
      sameSite: 'strict',
      path: '/api/auth/refresh-token',
      maxAge: config.jwt.refreshTokenMaxAge,
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
});

export default router;
