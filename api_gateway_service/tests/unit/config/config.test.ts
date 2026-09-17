jest.mock('dotenv', () => ({
  config: jest.fn(),
}));

describe('Config', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...originalEnv };
    delete process.env.PORT;
    delete process.env.HOST;
    delete process.env.JWT_SECRET;
    delete process.env.CORS_ORIGIN;
    delete process.env.AUTH_EXCLUDE_PATHS;
    delete process.env.ROUTES;
    delete process.env.REDIS_HOST;
    delete process.env.REDIS_PORT;
    delete process.env.PROXY_SECRET;
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it('should use default values when no env vars set', () => {
    process.env.ROUTES = '[]';
    const { default: config } = require('../../../src/config');
    expect(config.port).toBe(3000);
    expect(config.host).toBe('127.0.0.1');
    expect(config.auth.jwtSecret).toBe('change-me-in-production');
    expect(config.rateLimit.windowMs).toBe(900000);
    expect(config.rateLimit.max).toBe(100);
    expect(config.redis.host).toBe('127.0.0.1');
    expect(config.redis.port).toBe(6379);
  });

  it('should parse custom env values', () => {
    process.env.PORT = '4000';
    process.env.HOST = '0.0.0.0';
    process.env.JWT_SECRET = 'my-secret';
    process.env.ROUTES = '[]';
    const { default: config } = require('../../../src/config');
    expect(config.port).toBe(4000);
    expect(config.host).toBe('0.0.0.0');
    expect(config.auth.jwtSecret).toBe('my-secret');
  });

  it('should parse routes from JSON', () => {
    process.env.ROUTES = JSON.stringify([
      { prefix: '/api/test', target: 'http://localhost:9999' },
    ]);
    const { default: config } = require('../../../src/config');
    expect(config.routes).toHaveLength(1);
    expect(config.routes[0].prefix).toBe('/api/test');
  });

  it('should return empty routes on invalid JSON', () => {
    process.env.ROUTES = 'not-json';
    const { default: config } = require('../../../src/config');
    expect(config.routes).toEqual([]);
  });

  it('should parse CORS_ORIGIN with multiple origins', () => {
    process.env.CORS_ORIGIN = 'http://a.com,http://b.com';
    process.env.ROUTES = '[]';
    const { default: config } = require('../../../src/config');
    expect(config.cors.origin).toEqual(['http://a.com', 'http://b.com']);
  });

  it('should handle CORS_ORIGIN as *', () => {
    process.env.CORS_ORIGIN = '*';
    process.env.ROUTES = '[]';
    const { default: config } = require('../../../src/config');
    expect(config.cors.origin).toEqual(['*']);
  });

  it('should parse AUTH_EXCLUDE_PATHS', () => {
    process.env.AUTH_EXCLUDE_PATHS = '/health,/api/login';
    process.env.ROUTES = '[]';
    const { default: config } = require('../../../src/config');
    expect(config.auth.excludePaths).toEqual(['/health', '/api/login']);
  });
});
