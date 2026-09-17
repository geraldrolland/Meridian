import { getIdentifier, setRateLimitHeaders } from '../../../../src/middleware/ratelimit/utils';
import { createMockReq, createMockRes } from '../../../__mocks__/express';

describe('getIdentifier', () => {
  it('should return userId when baseOn is userId', () => {
    const req = createMockReq() as any;
    req.user = { userId: 'user-123' };
    expect(getIdentifier(req, 'userId')).toBe('user-123');
  });

  it('should fall back to ip when baseOn is userId but no user', () => {
    const req = createMockReq({ ip: '192.168.1.1' }) as any;
    expect(getIdentifier(req, 'userId')).toBe('192.168.1.1');
  });

  it('should return ip when baseOn is ip', () => {
    const req = createMockReq({ ip: '10.0.0.1' }) as any;
    expect(getIdentifier(req, 'ip')).toBe('10.0.0.1');
  });

  it('should fall back to socket.remoteAddress', () => {
    const req = createMockReq({ ip: undefined, socket: { remoteAddress: '172.16.0.1' } }) as any;
    expect(getIdentifier(req, 'ip')).toBe('172.16.0.1');
  });

  it('should return unknown if no ip at all', () => {
    const req = createMockReq({ ip: undefined, socket: {} }) as any;
    expect(getIdentifier(req, 'ip')).toBe('unknown');
  });
});

describe('setRateLimitHeaders', () => {
  it('should set correct headers', () => {
    const res = createMockRes();
    setRateLimitHeaders(res, 100, 95, 1726000000000);
    expect(res.setHeader).toHaveBeenCalledWith('X-RateLimit-Limit', 100);
    expect(res.setHeader).toHaveBeenCalledWith('X-RateLimit-Remaining', 95);
    expect(res.setHeader).toHaveBeenCalledWith('X-RateLimit-Reset', Math.ceil(1726000000000 / 1000));
  });

  it('should floor remaining to 0 when negative', () => {
    const res = createMockRes();
    setRateLimitHeaders(res, 100, -5, 1726000000000);
    expect(res.setHeader).toHaveBeenCalledWith('X-RateLimit-Remaining', 0);
  });
});
