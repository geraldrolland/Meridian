jest.mock('../../../src/config/database', () => ({
  default: { query: jest.fn() },
  __esModule: true,
}));
jest.mock('../../../src/config/redis', () => require('../../__mocks__/redis').default);

import { createMockReq, createMockRes, _resetRouterStack } from '../../__mocks__/express';
import pool from '../../../src/config/database';
import redis from '../../../src/config/redis';

const mockPool = jest.mocked(pool);
const mockRedis = jest.mocked(redis, { partial: true }) as any;

let readyHandler: (req: any, res: any, next: any) => Promise<void>;

beforeAll(async () => {
  const readyModule = await import('../../../src/routes/ready');
  const router = readyModule.default;
  const layer = router.stack.find((l: any) => l.route?.path === '/ready');
  readyHandler = layer.route.stack[0].handle;
});

afterEach(() => {
  _resetRouterStack();
});

describe('Ready Route', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPool.query.mockResolvedValue({ rows: [{ column: 1 }] } as any);
    mockRedis.ping.mockResolvedValue('PONG' as any);
  });

  it('should return 200 when db and redis are reachable', async () => {
    const req = createMockReq({ method: 'GET', url: '/ready', originalUrl: '/ready' });
    const res = createMockRes();
    const next = jest.fn();

    await readyHandler(req, res, next);

    expect(mockPool.query).toHaveBeenCalledWith('SELECT 1');
    expect(mockRedis.ping).toHaveBeenCalled();
    expect(res.json).toHaveBeenCalledWith({
      status: 'ok',
      checks: { db: 'ok', redis: 'ok' },
    });
  });

  it('should return 500 when database is unreachable', async () => {
    mockPool.query.mockRejectedValue(new Error('Connection refused'));

    const req = createMockReq({ method: 'GET', url: '/ready', originalUrl: '/ready' });
    const res = createMockRes();
    const next = jest.fn();

    await readyHandler(req, res, next);

    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({
      status: 'not_ok',
      checks: { db: 'not_ok', redis: 'ok' },
    });
  });

  it('should return 500 when redis is unreachable', async () => {
    mockRedis.ping.mockRejectedValue(new Error('Connection refused'));

    const req = createMockReq({ method: 'GET', url: '/ready', originalUrl: '/ready' });
    const res = createMockRes();
    const next = jest.fn();

    await readyHandler(req, res, next);

    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({
      status: 'not_ok',
      checks: { db: 'ok', redis: 'not_ok' },
    });
  });

  it('should return 500 when both db and redis are unreachable', async () => {
    mockPool.query.mockRejectedValue(new Error('Connection refused'));
    mockRedis.ping.mockRejectedValue(new Error('Connection refused'));

    const req = createMockReq({ method: 'GET', url: '/ready', originalUrl: '/ready' });
    const res = createMockRes();
    const next = jest.fn();

    await readyHandler(req, res, next);

    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({
      status: 'not_ok',
      checks: { db: 'not_ok', redis: 'not_ok' },
    });
  });
});
