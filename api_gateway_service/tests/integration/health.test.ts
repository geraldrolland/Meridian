jest.mock('../../src/config', () => ({
  __esModule: true,
  default: {
    jwt: { secret: 'test-secret' },
    auth: {
      jwtSecret: 'test-secret',
      excludePaths: ['/health', '/api/auth/login', '/api/auth/register', '/api/auth/refresh-token'],
    },
    rateLimit: { windowMs: 900000, max: 100 },
    routes: [],
  },
  logger: { info: jest.fn(), error: jest.fn(), warn: jest.fn() },
}));
jest.mock('../../src/config/redis', () => require('../__mocks__/redis').default);
jest.mock('../../src/middleware/cors', () => ({
  default: (_req: any, _res: any, next: any) => next(),
}));
jest.mock('../../src/proxy', () => {
  const expressModule = jest.requireActual('express');
  return { default: expressModule.Router() };
});

import request from 'supertest';
import jwt from 'jsonwebtoken';

const mockRedis = require('../__mocks__/redis').default;

let app: any;

beforeAll(async () => {
  const expressModule = jest.requireActual('express');
  const cookieParser = require('cookie-parser');
  const { authMiddleware } = require('../../src/middleware/auth');
  const { rateLimiter } = require('../../src/middleware/ratelimit');
  const { refreshTokenHandler } = require('../../src/handlers/refreshToken');
  const { errorHandler } = require('../../src/middleware/errorHandler');

  const testApp = expressModule();
  testApp.use(cookieParser());
  testApp.use(expressModule.json());
  testApp.get('/health', (_req: any, res: any) => res.json({ status: 'ok', timestamp: new Date().toISOString() }));
  testApp.use(authMiddleware);
  testApp.use(rateLimiter);
  testApp.post('/api/auth/refresh-token', refreshTokenHandler);
  testApp.use((_req: any, res: any) => res.status(404).json({ error: 'Route not found' }));
  testApp.use(errorHandler);
  app = testApp;
});

describe('Health Integration', () => {
  it('GET /health should return 200 with status ok', async () => {
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('status', 'ok');
    expect(res.body).toHaveProperty('timestamp');
  });

  it('GET /unknown-route without auth should return 401', async () => {
    const res = await request(app).get('/nonexistent');
    expect(res.status).toBe(401);
  });

  it('GET /unknown-route with auth should return 404', async () => {
    const token = jwt.sign({ sessionId: 'test-session' }, 'test-secret');
    mockRedis.get.mockResolvedValue(JSON.stringify({ userId: 'u1', role: 'admin', email: 'a@b.com' }));
    const res = await request(app)
      .get('/nonexistent')
      .set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(404);
    expect(res.body.error).toBe('Route not found');
  });
});

describe('Refresh Token Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should return 401 when no refresh cookie', async () => {
    const res = await request(app).post('/api/auth/refresh-token');
    expect(res.status).toBe(401);
    expect(res.body.error).toBe('Missing refresh token');
  });

  it('should return 200 and rotate tokens on valid refresh', async () => {
    const token = jwt.sign({ sessionId: 'sess-integ' }, 'test-secret');
    mockRedis.get.mockResolvedValue(JSON.stringify({ userId: 'u1', role: 'admin', email: 'a@b.com' }));
    mockRedis.del.mockResolvedValue(1);
    mockRedis.set.mockResolvedValue('OK');

    const res = await request(app)
      .post('/api/auth/refresh-token')
      .set('Cookie', `refresh=${token}`);

    expect(res.status).toBe(200);
    expect(res.body.accessToken).toBeDefined();
    expect(typeof res.body.accessToken).toBe('string');
  });

  it('should return 401 for expired refresh token', async () => {
    const token = jwt.sign({ sessionId: 'sess-exp' }, 'test-secret', { expiresIn: '-1s' });
    const res = await request(app)
      .post('/api/auth/refresh-token')
      .set('Cookie', `refresh=${token}`);
    expect(res.status).toBe(401);
  });
});
