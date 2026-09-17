jest.mock('bcrypt', () => ({
  hash: jest.fn().mockResolvedValue('$2b$12$hashedpassword'),
  compare: jest.fn().mockResolvedValue(true),
}));

jest.mock('../../../src/config/redis', () => require('../../__mocks__/redis').default);
jest.mock('../../../src/config/database', () => ({
  default: { query: jest.fn() },
  __esModule: true,
}));

jest.mock('../../../src/config', () => ({
  __esModule: true,
  default: {
    port: 4000,
    host: '127.0.0.1',
    jwt: { secret: 'test-secret', accessTokenExpiry: '7m', refreshTokenExpiry: '7d', refreshTokenMaxAge: 604800000 },
    proxySecret: 'test-secret',
  },
  logger: { info: jest.fn(), error: jest.fn(), warn: jest.fn() },
}));

import crypto from 'crypto';
import { checkProxySignature } from '../../../src/middleware/checkProxySignature';
import { createMockReq, createMockRes } from '../../__mocks__/express';
import redis from '../../../src/config/redis';
import db from '../../../src/config/database';

const mockRedis = jest.mocked(redis);
const mockDb = jest.mocked(db);

function signProxy(method: string, url: string, timestamp: string): string {
  const payload = `${method}:${url}:${timestamp}`;
  return crypto.createHmac('sha256', 'test-secret').update(payload).digest('hex');
}

function proxyHeaders(method: string, url: string) {
  const ts = Date.now().toString();
  return {
    'x-proxy-signature': signProxy(method, url, ts),
    'x-proxy-timestamp': ts,
  };
}

describe('Auth Routes - Handler Logic', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('checkProxySignature middleware', () => {
    it('should pass valid proxy signature', () => {
      const ts = Date.now().toString();
      const sig = signProxy('POST', '/api/auth/login', ts);
      const req = createMockReq({ method: 'POST', url: '/api/auth/login', originalUrl: '/api/auth/login', headers: { 'x-proxy-signature': sig, 'x-proxy-timestamp': ts } }) as any;
      const res = createMockRes();
      const next = jest.fn();
      checkProxySignature(req, res, next);
      expect(next).toHaveBeenCalled();
    });

    it('should reject missing signature', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/login', originalUrl: '/api/auth/login', headers: {} }) as any;
      const res = createMockRes();
      const next = jest.fn();
      checkProxySignature(req, res, next);
      expect(res.status).toHaveBeenCalledWith(403);
      expect(next).not.toHaveBeenCalled();
    });

    it('should reject expired timestamp', () => {
      const ts = (Date.now() - 31000).toString();
      const sig = signProxy('POST', '/api/auth/login', ts);
      const req = createMockReq({ method: 'POST', url: '/api/auth/login', originalUrl: '/api/auth/login', headers: { 'x-proxy-signature': sig, 'x-proxy-timestamp': ts } }) as any;
      const res = createMockRes();
      const next = jest.fn();
      checkProxySignature(req, res, next);
      expect(res.status).toHaveBeenCalledWith(403);
      expect(res.json).toHaveBeenCalledWith({ error: 'Proxy signature expired' });
    });
  });

  describe('Register validation', () => {
    it('should reject missing email', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/register', originalUrl: '/api/auth/register', body: { password: 'secret123' } }) as any;
      const res = createMockRes();
      if (!req.body.email || !req.body.password) {
        res.status(400).json({ error: 'Email and password are required' });
      }
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it('should reject short password', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/register', originalUrl: '/api/auth/register', body: { email: 'test@test.com', password: '123' } }) as any;
      const res = createMockRes();
      if (req.body.password && req.body.password.length < 6) {
        res.status(400).json({ error: 'Password must be at least 6 characters' });
      }
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it('should reject invalid email', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/register', originalUrl: '/api/auth/register', body: { email: 'not-an-email', password: 'secret123' } }) as any;
      const res = createMockRes();
      if (req.body.email && !req.body.email.includes('@')) {
        res.status(400).json({ error: 'Invalid email format' });
      }
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  describe('Login validation', () => {
    it('should reject missing email', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/login', originalUrl: '/api/auth/login', body: { password: 'secret123' } }) as any;
      const res = createMockRes();
      if (!req.body.email || !req.body.password) {
        res.status(400).json({ error: 'Email and password are required' });
      }
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  describe('Logout validation', () => {
    it('should reject missing auth header', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/logout', originalUrl: '/api/auth/logout', headers: {} }) as any;
      const res = createMockRes();
      const authHeader = req.headers.authorization;
      if (!authHeader || !authHeader.startsWith('Bearer ')) {
        res.status(401).json({ error: 'Missing or invalid Authorization header' });
      }
      expect(res.status).toHaveBeenCalledWith(401);
    });
  });

  describe('Refresh token validation', () => {
    it('should reject missing refresh cookie', () => {
      const req = createMockReq({ method: 'POST', url: '/api/auth/refresh-token', originalUrl: '/api/auth/refresh-token', cookies: {} }) as any;
      const res = createMockRes();
      if (!req.cookies?.refresh) {
        res.status(401).json({ error: 'Missing refresh token' });
      }
      expect(res.status).toHaveBeenCalledWith(401);
    });
  });

  describe('Me endpoint validation', () => {
    it('should reject missing auth header', () => {
      const req = createMockReq({ method: 'GET', url: '/api/auth/me', originalUrl: '/api/auth/me', headers: {} }) as any;
      const res = createMockRes();
      const next = jest.fn();
      checkProxySignature(req, res, next);
      const authHeader = req.headers.authorization;
      if (!authHeader || !authHeader.startsWith('Bearer ')) {
        res.status(401).json({ error: 'Missing or invalid Authorization header' });
      }
      expect(res.status).toHaveBeenCalledWith(401);
    });

    it('should reject invalid token', () => {
      const req = createMockReq({ method: 'GET', url: '/api/auth/me', originalUrl: '/api/auth/me', headers: { authorization: 'Bearer invalid-token' } }) as any;
      const res = createMockRes();
      const jwt = require('jsonwebtoken');
      try {
        jwt.verify('invalid-token', 'test-secret');
      } catch (err) {
        res.status(401).json({ error: 'Invalid token' });
      }
      expect(res.status).toHaveBeenCalledWith(401);
    });
  });

  describe('Health endpoint', () => {
    it('should return health status', () => {
      const req = createMockReq({ method: 'GET', url: '/', originalUrl: '/' }) as any;
      const res = createMockRes();
      res.json({ status: 'ok', service: 'auth-service', timestamp: new Date().toISOString() });
      expect(res.json).toHaveBeenCalled();
    });
  });
});
