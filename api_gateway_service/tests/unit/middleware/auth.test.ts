import jwt from 'jsonwebtoken';
import { authMiddleware } from '../../../src/middleware/auth';
import { createMockReq, createMockRes, createMockNext } from '../../__mocks__/express';
import redis from '../../../src/config/redis';

jest.mock('../../../src/config/redis', () => require('../../__mocks__/redis').default);

jest.mock('../../../src/config', () => {
  return {
    __esModule: true,
    default: {
      auth: {
        jwtSecret: 'test-secret',
        excludePaths: ['/health', '/api/auth/login'],
      },
    },
  };
});

const mockRedis = jest.mocked(redis);

describe('Auth Middleware', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should skip auth for excluded paths', async () => {
    const req = createMockReq({ path: '/health' });
    const res = createMockRes();
    const next = createMockNext();
    await authMiddleware(req, res, next);
    expect(next).toHaveBeenCalled();
    expect(res.status).not.toHaveBeenCalled();
  });

  it('should return 401 if no Authorization header', async () => {
    const req = createMockReq({ path: '/api/users', headers: {} });
    const res = createMockRes();
    const next = createMockNext();
    await authMiddleware(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it('should return 401 if no sessionId in token', async () => {
    const token = jwt.sign({}, 'test-secret');
    const req = createMockReq({ path: '/api/users', headers: { authorization: `Bearer ${token}` } });
    const res = createMockRes();
    const next = createMockNext();
    await authMiddleware(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it('should return 401 if session not found in Redis', async () => {
    const token = jwt.sign({ sessionId: 'sess-123' }, 'test-secret');
    mockRedis.get.mockResolvedValue(null);
    const req = createMockReq({ path: '/api/users', headers: { authorization: `Bearer ${token}` } });
    const res = createMockRes();
    const next = createMockNext();
    await authMiddleware(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it('should attach user and call next on valid token', async () => {
    const token = jwt.sign({ sessionId: 'sess-123' }, 'test-secret');
    mockRedis.get.mockResolvedValue(JSON.stringify({ userId: 'u1', role: 'admin', email: 'a@b.com' }));
    const req = createMockReq({ path: '/api/users', headers: { authorization: `Bearer ${token}` } });
    const res = createMockRes();
    const next = createMockNext();
    await authMiddleware(req, res, next);
    expect(req.user).toEqual({ userId: 'u1', role: 'admin', email: 'a@b.com' });
    expect(next).toHaveBeenCalled();
  });

  it('should return 401 on invalid token', async () => {
    const req = createMockReq({ path: '/api/users', headers: { authorization: 'Bearer invalid' } });
    const res = createMockRes();
    const next = createMockNext();
    await authMiddleware(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
  });
});
