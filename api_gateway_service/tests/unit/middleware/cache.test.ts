import {
  buildCacheKey,
  cacheMiddleware,
  invalidateAllVideoCache,
  invalidateVideoCache,
  isJsonContentType,
} from '../../../src/middleware/cache';
import { AuthenticatedRequest } from '../../../src/types';
import { createMockReq, createMockRes, createMockNext } from '../../__mocks__/express';
import redis from '../../../src/config/redis';

jest.mock('../../../src/config/redis', () => require('../../__mocks__/redis').default);

jest.mock('../../../src/config', () => ({
  __esModule: true,
  default: {
    cache: { routes: ['/api/video'], ttlSeconds: 420 },
  },
}));

jest.mock('../../../src/middleware/logger', () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

const mockRedis = jest.mocked(redis);

function cacheableReq(overrides: Record<string, unknown> = {}): AuthenticatedRequest {
  return createMockReq({
    path: '/api/video/123',
    originalUrl: '/api/video/123',
    method: 'GET',
    user: { userId: '42', email: 'u@u.com' },
    ...overrides,
  }) as unknown as AuthenticatedRequest;
}

/** Lets the store-then-flush promise chain inside res.end settle. */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 10));
}

describe('cacheMiddleware — request phase', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRedis.get.mockResolvedValue(null);
  });

  it('skips non-GET requests without touching Redis', async () => {
    const req = cacheableReq({ method: 'POST' });
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).toHaveBeenCalled();
    expect(mockRedis.get).not.toHaveBeenCalled();
  });

  it('skips paths outside CACHE_ROUTES', async () => {
    const req = cacheableReq({ path: '/health', originalUrl: '/health' });
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).toHaveBeenCalled();
    expect(mockRedis.get).not.toHaveBeenCalled();
  });

  it('skips when there is no authenticated user', async () => {
    const req = cacheableReq({ user: undefined });
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).toHaveBeenCalled();
    expect(mockRedis.get).not.toHaveBeenCalled();
  });

  it('flushes all cached video responses on DELETE under CACHE_ROUTES', async () => {
    mockRedis.scan.mockResolvedValueOnce(['0', ['cache:resp:42:/api/video/123']]);
    const req = cacheableReq({ method: 'DELETE' });
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(mockRedis.scan).toHaveBeenCalledWith(
      '0',
      'MATCH',
      'cache:resp:*:/api/video*',
      'COUNT',
      100
    );
    expect(mockRedis.del).toHaveBeenCalledWith('cache:resp:42:/api/video/123');
    expect(next).toHaveBeenCalled();
    expect(mockRedis.get).not.toHaveBeenCalled();
  });

  it('does not flush on DELETE outside CACHE_ROUTES', async () => {
    const req = cacheableReq({
      method: 'DELETE',
      path: '/health',
      originalUrl: '/health',
    });
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(mockRedis.scan).not.toHaveBeenCalled();
    expect(next).toHaveBeenCalled();
  });

  it('DELETE proceeds even when the flush fails (fail-open)', async () => {
    mockRedis.scan.mockRejectedValueOnce(new Error('down'));
    const req = cacheableReq({ method: 'DELETE' });
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).toHaveBeenCalled();
  });

  it('calls next on a cache miss and installs the response capture', async () => {
    const req = cacheableReq();
    const res = createMockRes();
    const originalEnd = res.end;
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(mockRedis.get).toHaveBeenCalledWith('cache:resp:42:/api/video/123');
    expect(next).toHaveBeenCalled();
    expect(res.end).not.toBe(originalEnd);
  });

  it('replays a cache hit without calling next', async () => {
    const stored = {
      status: 200,
      contentType: 'application/json; charset=utf-8',
      body: '{"id":"123","status":"COMPLETED"}',
    };
    mockRedis.get.mockResolvedValue(JSON.stringify(stored));

    const req = cacheableReq();
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.setHeader).toHaveBeenCalledWith('Content-Type', stored.contentType);
    expect(res.send).toHaveBeenCalled();
    const sent = (res.send as jest.Mock).mock.calls[0][0] as Buffer;
    expect(Buffer.isBuffer(sent)).toBe(true);
    expect(sent.toString('utf8')).toBe(stored.body);
  });

  it('treats a malformed cache entry as a miss', async () => {
    mockRedis.get.mockResolvedValue('not-json{');

    const req = cacheableReq();
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).toHaveBeenCalled();
  });

  it('fails open when Redis read errors', async () => {
    mockRedis.get.mockRejectedValue(new Error('connection lost'));

    const req = cacheableReq();
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    expect(next).toHaveBeenCalled();
  });
});

describe('cacheMiddleware — response phase', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRedis.get.mockResolvedValue(null);
    mockRedis.set.mockResolvedValue('OK');
  });

  it('stores a 200 JSON response with the configured TTL before flushing', async () => {
    const req = cacheableReq();
    const res = createMockRes();
    const originalEnd = res.end;
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
    res.end('{"id":"123"}');
    await flush();

    expect(mockRedis.set).toHaveBeenCalledTimes(1);
    const [key, value, flag, ttl] = mockRedis.set.mock.calls[0];
    expect(key).toBe('cache:resp:42:/api/video/123');
    expect(flag).toBe('EX');
    expect(ttl).toBe(420);
    const stored = JSON.parse(value);
    expect(stored.status).toBe(200);
    expect(stored.contentType).toBe('application/json; charset=utf-8');
    expect(stored.body).toBe('{"id":"123"}');
    expect(originalEnd).toHaveBeenCalled();
  });

  it('captures content type via write + setHeader fallback', async () => {
    const req = cacheableReq();
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    res.setHeader('Content-Type', 'application/json');
    res.write('{"chunk":');
    res.end('true}');
    await flush();

    expect(mockRedis.set).toHaveBeenCalledTimes(1);
    const stored = JSON.parse(mockRedis.set.mock.calls[0][1]);
    expect(stored.body).toBe('{"chunk":true}');
  });

  it('does not store a 200 with non-JSON content type', async () => {
    const req = cacheableReq();
    const res = createMockRes();
    const originalEnd = res.end;
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<html></html>');
    await flush();

    expect(mockRedis.set).not.toHaveBeenCalled();
    expect(originalEnd).toHaveBeenCalled();
  });

  it('does not store a 200 with no content type', async () => {
    const req = cacheableReq();
    const res = createMockRes();
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    res.end('no-header');
    await flush();

    expect(mockRedis.set).not.toHaveBeenCalled();
  });

  it('does not store a non-200 JSON response', async () => {
    const req = cacheableReq();
    const res = createMockRes();
    const originalEnd = res.end;
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    res.statusCode = 500;
    res.writeHead(500, { 'content-type': 'application/json' });
    res.end('{"error":"boom"}');
    await flush();

    expect(mockRedis.set).not.toHaveBeenCalled();
    expect(originalEnd).toHaveBeenCalled();
  });

  it('still flushes the response when the Redis store fails', async () => {
    mockRedis.set.mockRejectedValue(new Error('redis down'));

    const req = cacheableReq();
    const res = createMockRes();
    const originalEnd = res.end;
    const next = createMockNext();

    await cacheMiddleware(req, res, next);

    res.writeHead(200, { 'content-type': 'application/json' });
    res.end('{"ok":true}');
    await flush();

    expect(originalEnd).toHaveBeenCalled();
  });
});

describe('isJsonContentType', () => {
  it.each([
    ['application/json', true],
    ['application/json; charset=utf-8', true],
    ['APPLICATION/JSON', true],
    ['application/problem+json', true],
    ['text/html', false],
    ['text/plain', false],
    ['', false],
    [undefined, false],
    [null, false],
  ])('%s → %s', (value, expected) => {
    expect(isJsonContentType(value as string | null | undefined)).toBe(expected);
  });
});

describe('buildCacheKey', () => {
  it('concatenates user id with the full request URL', () => {
    expect(buildCacheKey('/api/video/abc?full=true', '7')).toBe(
      'cache:resp:7:/api/video/abc?full=true'
    );
  });
});

describe('invalidateVideoCache', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('scans and deletes matching keys', async () => {
    mockRedis.scan.mockResolvedValueOnce(['0', ['cache:resp:42:/api/video/v9']]);

    await invalidateVideoCache('v9');

    expect(mockRedis.scan).toHaveBeenCalledWith(
      '0',
      'MATCH',
      'cache:resp:*:/api/video/v9*',
      'COUNT',
      100
    );
    expect(mockRedis.del).toHaveBeenCalledWith('cache:resp:42:/api/video/v9');
  });

  it('swallows Redis errors (fail-open)', async () => {
    mockRedis.scan.mockRejectedValueOnce(new Error('down'));

    await expect(invalidateVideoCache('v9')).resolves.toBeUndefined();
  });
});

describe('invalidateAllVideoCache', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('scans the whole video namespace and deletes matching keys', async () => {
    mockRedis.scan.mockResolvedValueOnce([
      '0',
      ['cache:resp:42:/api/video/v9', 'cache:resp:42:/api/video?v=1'],
    ]);

    await invalidateAllVideoCache();

    expect(mockRedis.scan).toHaveBeenCalledWith(
      '0',
      'MATCH',
      'cache:resp:*:/api/video*',
      'COUNT',
      100
    );
    expect(mockRedis.del).toHaveBeenCalledWith(
      'cache:resp:42:/api/video/v9',
      'cache:resp:42:/api/video?v=1'
    );
  });

  it('swallows Redis errors (fail-open)', async () => {
    mockRedis.scan.mockRejectedValueOnce(new Error('down'));

    await expect(invalidateAllVideoCache()).resolves.toBeUndefined();
  });
});
