jest.mock('../../src/config', () => ({
  __esModule: true,
  default: {
    jwt: { secret: 'test-secret' },
    auth: {
      jwtSecret: 'test-secret',
      excludePaths: ['/health', '/ready', '/api/auth/login', '/api/auth/register', '/api/auth/refresh-token'],
    },
    rateLimit: { windowMs: 900000, max: 100 },
    routes: [
      { prefix: '/api/auth', target: 'http://auth-service:4000' },
      { prefix: '/api/video', target: 'http://video-service:8000' },
    ],
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

const mockRedis = require('../__mocks__/redis').default;

let app: any;

beforeAll(async () => {
  const expressModule = jest.requireActual('express');
  const cookieParser = require('cookie-parser');
  const { readyHandler } = require('../../src/routes/ready');
  const { authMiddleware } = require('../../src/middleware/auth');
  const { rateLimiter } = require('../../src/middleware/ratelimit');
  const { errorHandler } = require('../../src/middleware/errorHandler');

  const testApp = expressModule();
  testApp.use(cookieParser());
  testApp.get('/health', (_req: any, res: any) => res.json({ status: 'ok' }));
  testApp.get('/ready', readyHandler);
  testApp.use(authMiddleware);
  testApp.use(rateLimiter);
  testApp.use((_req: any, res: any) => res.status(404).json({ error: 'Route not found' }));
  testApp.use(errorHandler);
  app = testApp;
});

describe('Ready Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRedis.ping.mockResolvedValue('PONG');
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
    }) as any;
  });

  afterEach(() => {
    delete (global as any).fetch;
  });

  it('GET /ready returns 200 when redis and upstreams are healthy', async () => {
    const res = await request(app).get('/ready');

    expect(res.status).toBe(200);
    expect(res.body).toEqual({
      status: 'ok',
      checks: {
        redis: 'ok',
        '/api/auth': 'ok',
        '/api/video': 'ok',
      },
    });
    expect(mockRedis.ping).toHaveBeenCalled();
    expect(global.fetch).toHaveBeenCalledWith(
      'http://auth-service:4000/ready',
      expect.anything(),
    );
    expect(global.fetch).toHaveBeenCalledWith(
      'http://video-service:8000/ready',
      expect.anything(),
    );
  });

  it('GET /ready returns 500 when redis is down', async () => {
    mockRedis.ping.mockRejectedValue(new Error('Connection refused'));

    const res = await request(app).get('/ready');

    expect(res.status).toBe(500);
    expect(res.body.status).toBe('not_ok');
    expect(res.body.checks.redis).toBe('not_ok');
    expect(res.body.checks['/api/auth']).toBe('ok');
    expect(res.body.checks['/api/video']).toBe('ok');
  });

  it('GET /ready returns 500 when an upstream is down', async () => {
    global.fetch = jest.fn().mockImplementation((url: string) => {
      if (url.includes('auth-service')) {
        return Promise.reject(new Error('connect ECONNREFUSED'));
      }
      return Promise.resolve({ ok: true, status: 200 });
    }) as any;

    const res = await request(app).get('/ready');

    expect(res.status).toBe(500);
    expect(res.body.status).toBe('not_ok');
    expect(res.body.checks.redis).toBe('ok');
    expect(res.body.checks['/api/auth']).toBe('not_ok');
    expect(res.body.checks['/api/video']).toBe('ok');
  });

  it('GET /ready is excluded from auth (no 401)', async () => {
    const res = await request(app).get('/ready');
    expect(res.status).toBe(200);
  });
});
