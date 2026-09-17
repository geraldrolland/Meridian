jest.mock('../../src/config/redis', () => require('../__mocks__/redis').default);
jest.mock('../../src/proxy', () => {
  const expressModule = jest.requireActual('express');
  return { default: expressModule.Router() };
});
jest.mock('../../src/middleware/cors', () => ({
  default: (_req: any, _res: any, next: any) => next(),
}));

let app: any;

beforeAll(async () => {
  const expressModule = jest.requireActual('express');
  const cookieParser = require('cookie-parser');
  const helmet = require('helmet');
  const config = require('../../src/config').default;
  const { authMiddleware } = require('../../src/middleware/auth');
  const { rateLimiter } = require('../../src/middleware/ratelimit');
  const { refreshTokenHandler } = require('../../src/handlers/refreshToken');
  const { requestLogger } = require('../../src/middleware/logger');
  const { errorHandler } = require('../../src/middleware/errorHandler');

  const testApp = expressModule();
  testApp.use(helmet());
  testApp.use(cookieParser());
  testApp.use(expressModule.json());
  testApp.use(requestLogger);
  testApp.get('/health', (_req: any, res: any) => res.json({ status: 'ok', timestamp: new Date().toISOString() }));
  testApp.use(authMiddleware);
  testApp.use(rateLimiter);
  testApp.post('/api/auth/refresh-token', refreshTokenHandler);
  testApp.use((_req: any, res: any) => res.status(404).json({ error: 'Route not found' }));
  testApp.use(errorHandler);
  app = testApp;
});

import request from 'supertest';

describe('Smoke Tests', () => {
  it('should start the server', () => {
    expect(app).toBeDefined();
  });

  it('GET /health should return 200', async () => {
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
    expect(res.body.timestamp).toBeDefined();
  });
});
