import { RateLimitByFixedWindow } from '../../../../src/middleware/ratelimit/fixedWindow';
import { createMockReq, createMockRes } from '../../../__mocks__/express';
import redis from '../../../../src/config/redis';

jest.mock('../../../../src/config/redis', () => require('../../../__mocks__/redis').default);

jest.mock('../../../../src/config', () => {
  return {
    __esModule: true,
    default: {
      routes: [],
      rateLimit: { windowMs: 900000, max: 100 },
    },
  };
});

const mockRedis = jest.mocked(redis);

describe('RateLimitByFixedWindow', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should allow request under limit', async () => {
    mockRedis.incr.mockResolvedValue(50);
    mockRedis.ttl.mockResolvedValue(800);
    const req = createMockReq({ ip: '127.0.0.1' }) as any;
    const res = createMockRes();
    const result = await RateLimitByFixedWindow(req, res, 'ip', '/api/users');
    expect(result).toBe(true);
  });

  it('should deny request over limit', async () => {
    mockRedis.incr.mockResolvedValue(101);
    mockRedis.ttl.mockResolvedValue(100);
    const req = createMockReq({ ip: '127.0.0.1' }) as any;
    const res = createMockRes();
    const result = await RateLimitByFixedWindow(req, res, 'ip', '/api/users');
    expect(result).toBe(false);
    expect(res.status).toHaveBeenCalledWith(429);
  });

  it('should set expiry on first request', async () => {
    mockRedis.incr.mockResolvedValue(1);
    mockRedis.expire.mockResolvedValue(1);
    mockRedis.ttl.mockResolvedValue(900);
    const req = createMockReq({ ip: '127.0.0.1' }) as any;
    const res = createMockRes();
    await RateLimitByFixedWindow(req, res, 'ip', '/api/users');
    expect(mockRedis.expire).toHaveBeenCalledWith(expect.any(String), 900);
  });
});
