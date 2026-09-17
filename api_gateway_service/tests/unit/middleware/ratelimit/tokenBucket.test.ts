import { RateLimitByTokenBucket } from '../../../../src/middleware/ratelimit/tokenBucket';
import { createMockReq, createMockRes } from '../../../__mocks__/express';
import redis from '../../../../src/config/redis';

jest.mock('../../../../src/config/redis', () => require('../../../__mocks__/redis').default);

jest.mock('../../../../src/config', () => {
  return {
    __esModule: true,
    default: {
      routes: [],
      rateLimit: { windowMs: 900000, max: 10 },
    },
  };
});

const mockRedis = jest.mocked(redis);

describe('RateLimitByTokenBucket', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should allow when tokens available', async () => {
    mockRedis.eval.mockResolvedValue([1, '9']);
    const req = createMockReq({ ip: '127.0.0.1' }) as any;
    const res = createMockRes();
    const result = await RateLimitByTokenBucket(req, res, 'ip', '/api/payment');
    expect(result).toBe(true);
  });

  it('should deny when no tokens available', async () => {
    mockRedis.eval.mockResolvedValue([0, '500']);
    const req = createMockReq({ ip: '127.0.0.1' }) as any;
    const res = createMockRes();
    const result = await RateLimitByTokenBucket(req, res, 'ip', '/api/payment');
    expect(result).toBe(false);
    expect(res.status).toHaveBeenCalledWith(429);
    expect(res.setHeader).toHaveBeenCalledWith('Retry-After', 1);
  });

  it('should set rate limit headers on allowed request', async () => {
    mockRedis.eval.mockResolvedValue([1, '8']);
    const req = createMockReq({ ip: '127.0.0.1' }) as any;
    const res = createMockRes();
    await RateLimitByTokenBucket(req, res, 'ip', '/api/payment');
    expect(res.setHeader).toHaveBeenCalledWith('X-RateLimit-Limit', 10);
    expect(res.setHeader).toHaveBeenCalledWith('X-RateLimit-Remaining', 8);
  });
});
