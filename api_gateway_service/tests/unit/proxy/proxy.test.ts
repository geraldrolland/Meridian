jest.mock('express', () => ({
  Router: jest.fn(() => ({
    use: jest.fn(),
  })),
}));

jest.mock('../../../src/config', () => ({
  __esModule: true,
  default: {
    proxySecret: 'test-proxy-secret',
    routes: [
      {
        prefix: '/api/test',
        target: 'http://test-service:4000',
        rewrite: false,
      },
    ],
  },
}));

jest.mock('../../../src/middleware/logger', () => ({
  logger: {
    info: jest.fn(),
    error: jest.fn(),
  },
}));

let proxyReqHandler: (proxyReq: any, req: any) => void;
let errorHandler: (err: any, req: any, res: any) => void;

beforeAll(() => {
  const { getCapturedOptions } = require('../../__mocks__/http-proxy-middleware');
  require('../../../src/proxy/index');
  const options = getCapturedOptions();
  proxyReqHandler = options.on.proxyReq;
  errorHandler = options.on.error;
});

describe('Proxy Module', () => {
  describe('proxyReq handler', () => {
    it('should set session cookie when req.user exists', () => {
      const mockProxyReq = {
        getHeader: jest.fn().mockReturnValue(''),
        setHeader: jest.fn(),
      };
      const req = {
        method: 'GET',
        url: '/api/test/users',
        user: { userId: 'u1', role: 'admin', email: 'a@b.com' },
      };

      proxyReqHandler(mockProxyReq, req);

      const cookieArg = mockProxyReq.setHeader.mock.calls.find(
        (call: any[]) => call[0] === 'cookie'
      );
      expect(cookieArg).toBeDefined();

      const cookieValue = cookieArg![1];
      expect(cookieValue).toMatch(/^session=/);

      const decoded = decodeURIComponent(cookieValue.split('=')[1]);
      expect(JSON.parse(decoded)).toEqual({
        userId: 'u1',
        role: 'admin',
        email: 'a@b.com',
      });
    });

    it('should append session cookie to existing cookies', () => {
      const mockProxyReq = {
        getHeader: jest.fn().mockReturnValue('existing=value'),
        setHeader: jest.fn(),
      };
      const req = {
        method: 'POST',
        url: '/api/test/items',
        user: { userId: 'u2', role: 'user', email: 'x@y.com' },
      };

      proxyReqHandler(mockProxyReq, req);

      const cookieArg = mockProxyReq.setHeader.mock.calls.find(
        (call: any[]) => call[0] === 'cookie'
      );
      expect(cookieArg).toBeDefined();
      expect(cookieArg![1]).toMatch(/^existing=value; session=/);
    });

    it('should skip cookie when req.user is undefined', () => {
      const mockProxyReq = {
        getHeader: jest.fn().mockReturnValue(''),
        setHeader: jest.fn(),
      };
      const req = {
        method: 'GET',
        url: '/api/test/public',
      };

      proxyReqHandler(mockProxyReq, req);

      const cookieArg = mockProxyReq.setHeader.mock.calls.find(
        (call: any[]) => call[0] === 'cookie'
      );
      expect(cookieArg).toBeUndefined();
    });

    it('should set proxy signature headers on the Express request', () => {
      const { signProxyRequest } = require('../../../src/proxy/index');
      const req = {
        method: 'GET',
        url: '/api/test/data',
        originalUrl: '/api/test/data',
        headers: {} as Record<string, string>,
      };
      const next = jest.fn();

      signProxyRequest(req, {} as any, next);

      expect(req.headers['x-proxy-signature']).toEqual(expect.any(String));
      expect(Number(req.headers['x-proxy-timestamp'])).toBeGreaterThan(0);
      expect(next).toHaveBeenCalled();
    });

    it('should log proxy request', () => {
      const { logger } = require('../../../src/middleware/logger');
      const mockProxyReq = {
        getHeader: jest.fn().mockReturnValue(''),
        setHeader: jest.fn(),
      };
      const req = { method: 'GET', url: '/api/test/data' };

      proxyReqHandler(mockProxyReq, req);

      expect(logger.info).toHaveBeenCalledWith('Proxying request', {
        from: '/api/test/data',
        to: 'http://test-service:4000/api/test/data',
        prefix: '/api/test',
      });
    });
  });

  describe('error handler', () => {
    it('should return 502 on proxy error', () => {
      const mockRes = {
        status: jest.fn().mockReturnThis(),
        json: jest.fn(),
      };

      errorHandler(new Error('Connection refused'), {}, mockRes);

      expect(mockRes.status).toHaveBeenCalledWith(502);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Bad gateway - upstream service unavailable',
      });
    });
  });
});
