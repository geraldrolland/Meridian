import { Request } from 'express';

/**
 * Represents a user record from the `users` table in PostgreSQL.
 *
 * @property id - Auto-incrementing primary key
 * @property email - Unique email address used as the login identifier
 * @property hash_password - bcrypt-hashed password (12 salt rounds)
 * @property created_at - Timestamp of account creation
 */
export interface User {
  id: number;
  email: string;
  hash_password: string;
  created_at: Date;
}

/**
 * Session payload stored in Redis as `session:<sessionId>`.
 * Serialized as JSON with a 7-day TTL.
 *
 * @property userId - The user's primary key from the `users` table
 * @property email - The user's email address
 */
export interface SessionData {
  userId: number;
  email: string;
}

/**
 * Decoded JWT payload structure used for both access and refresh tokens.
 * The `sessionId` links the token to a Redis session record.
 *
 * @property sessionId - UUID v4 identifying the active session
 */
export interface JwtPayload {
  sessionId: string;
}

/**
 * Extended Express Request that carries authenticated session data.
 * Populated by route handlers after JWT verification and session lookup.
 *
 * @property user - Session data (userId, email) if the request is authenticated
 */
export interface AuthenticatedRequest extends Request {
  user?: SessionData;
}
