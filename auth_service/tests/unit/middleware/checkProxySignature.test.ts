import crypto from 'crypto';
import { checkProxySignature } from '../../../src/middleware/checkProxySignature';
import { createMockReq, createMockRes, createMockNext } from '../../__mocks__/express';

jest.mock('../../../src/config', () => {
  return {
    __esModule: true,
    default: {
      proxySecret: 'test-secret',
    },
  };
});

function signPayload(method: string, url: string, timestamp: string): string {
  const payload = `${method}:${url}:${timestamp}`;
  return crypto.createHmac('sha256', 'test-secret').update(payload).digest('hex');
}

describe('Check Proxy Signature Middleware', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should return 403 if no proxy signature header', () => {
    const req = createMockReq({
      method: 'POST',
      url: '/api/auth/login',
      headers: { 'x-proxy-timestamp': Date.now().toString() },
    }) as any;
    const res = createMockRes();
    const next = createMockNext();
    checkProxySignature(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(next).not.toHaveBeenCalled();
  });

  it('should return 403 if no proxy timestamp header', () => {
    const req = createMockReq({
      method: 'POST',
      url: '/api/auth/login',
      headers: { 'x-proxy-signature': 'abc' },
    }) as any;
    const res = createMockRes();
    const next = createMockNext();
    checkProxySignature(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(next).not.toHaveBeenCalled();
  });

  it('should return 403 if signature is invalid', () => {
    const timestamp = Date.now().toString();
    const fakeSig = 'a'.repeat(64);
    const req = createMockReq({
      method: 'POST',
      url: '/api/auth/login',
      headers: {
        'x-proxy-signature': fakeSig,
        'x-proxy-timestamp': timestamp,
      },
    }) as any;
    const res = createMockRes();
    const next = createMockNext();
    checkProxySignature(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(next).not.toHaveBeenCalled();
  });

  it('should return 403 if timestamp exceeds 30 seconds', () => {
    const oldTimestamp = (Date.now() - 31000).toString();
    const signature = signPayload('POST', '/api/auth/login', oldTimestamp);
    const req = createMockReq({
      method: 'POST',
      url: '/api/auth/login',
      headers: {
        'x-proxy-signature': signature,
        'x-proxy-timestamp': oldTimestamp,
      },
    }) as any;
    const res = createMockRes();
    const next = createMockNext();
    checkProxySignature(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith({ error: 'Proxy signature expired' });
    expect(next).not.toHaveBeenCalled();
  });

  it('should return 403 if timestamp is not a valid number', () => {
    const req = createMockReq({
      method: 'POST',
      url: '/api/auth/login',
      headers: {
        'x-proxy-signature': 'abc',
        'x-proxy-timestamp': 'not-a-number',
      },
    }) as any;
    const res = createMockRes();
    const next = createMockNext();
    checkProxySignature(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(next).not.toHaveBeenCalled();
  });

  it('should call next if signature is valid', () => {
    const timestamp = Date.now().toString();
    const signature = signPayload('POST', '/api/auth/login', timestamp);
    const req = createMockReq({
      method: 'POST',
      url: '/api/auth/login',
      originalUrl: '/api/auth/login',
      headers: {
        'x-proxy-signature': signature,
        'x-proxy-timestamp': timestamp,
      },
    }) as any;
    const res = createMockRes();
    const next = createMockNext();
    checkProxySignature(req, res, next);
    expect(next).toHaveBeenCalled();
    expect(res.status).not.toHaveBeenCalled();
  });
});
