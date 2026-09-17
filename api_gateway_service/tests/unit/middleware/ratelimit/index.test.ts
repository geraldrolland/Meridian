import { rateLimiter } from '../../../../src/middleware/ratelimit';
import { createMockReq, createMockRes, createMockNext } from '../../../__mocks__/express';

jest.mock('../../../../src/middleware/ratelimit/fixedWindow', () => ({
  RateLimitByFixedWindow: jest.fn().mockResolvedValue(true),
}));
jest.mock('../../../../src/middleware/ratelimit/tokenBucket', () => ({
  RateLimitByTokenBucket: jest.fn().mockResolvedValue(true),
}));

describe('Rate Limiter Middleware', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should call next when allowed', async () => {
    const req = createMockReq({ path: '/api/customer/123' }) as any;
    const res = createMockRes();
    const next = createMockNext();
    await rateLimiter(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it('should not call next when denied', async () => {
    const { RateLimitByFixedWindow } = require('../../../../src/middleware/ratelimit/fixedWindow');
    RateLimitByFixedWindow.mockResolvedValue(false);
    const req = createMockReq({ path: '/api/customer/123' }) as any;
    const res = createMockRes();
    const next = createMockNext();
    await rateLimiter(req, res, next);
    expect(next).not.toHaveBeenCalled();
  });

  it('should use userId when user is present', async () => {
    const { RateLimitByFixedWindow } = require('../../../../src/middleware/ratelimit/fixedWindow');
    const req = createMockReq({ path: '/api/customer/123' }) as any;
    req.user = { userId: 'user-1', role: 'admin', email: 'a@b.com' };
    const res = createMockRes();
    const next = createMockNext();
    await rateLimiter(req, res, next);
    expect(RateLimitByFixedWindow).toHaveBeenCalledWith(req, res, 'userId', '*');
  });

  it('should use ip when no user', async () => {
    const { RateLimitByFixedWindow } = require('../../../../src/middleware/ratelimit/fixedWindow');
    const req = createMockReq({ path: '/api/customer/123' }) as any;
    const res = createMockRes();
    const next = createMockNext();
    await rateLimiter(req, res, next);
    expect(RateLimitByFixedWindow).toHaveBeenCalledWith(req, res, 'ip', '*');
  });

  it('should use tokenBucket for /api/video', async () => {
    const { RateLimitByTokenBucket } = require('../../../../src/middleware/ratelimit/tokenBucket');
    const req = createMockReq({ path: '/api/video/123' }) as any;
    const res = createMockRes();
    const next = createMockNext();
    await rateLimiter(req, res, next);
    expect(RateLimitByTokenBucket).toHaveBeenCalledWith(req, res, 'ip', '/api/video');
  });

  it('should fallback to fixedWindow for unmatched routes', async () => {
    const { RateLimitByFixedWindow } = require('../../../../src/middleware/ratelimit/fixedWindow');
    const req = createMockReq({ path: '/api/unknown/route' }) as any;
    const res = createMockRes();
    const next = createMockNext();
    await rateLimiter(req, res, next);
    expect(RateLimitByFixedWindow).toHaveBeenCalled();
  });
});
