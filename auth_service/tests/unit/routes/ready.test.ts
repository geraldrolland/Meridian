jest.mock('../../../src/config/database', () => ({
  default: { query: jest.fn() },
  __esModule: true,
}));

import { createMockReq, createMockRes, _resetRouterStack } from '../../__mocks__/express';
import pool from '../../../src/config/database';

const mockPool = jest.mocked(pool);

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
  });

  it('should return 200 when database is reachable', async () => {
    mockPool.query.mockResolvedValue({ rows: [{ column: 1 }] } as any);

    const req = createMockReq({ method: 'GET', url: '/ready', originalUrl: '/ready' });
    const res = createMockRes();
    const next = jest.fn();

    await readyHandler(req, res, next);

    expect(mockPool.query).toHaveBeenCalledWith('SELECT 1');
    expect(res.json).toHaveBeenCalledWith({ status: 'ok', db: 'ok' });
  });

  it('should return 500 when database is unreachable', async () => {
    mockPool.query.mockRejectedValue(new Error('Connection refused'));

    const req = createMockReq({ method: 'GET', url: '/ready', originalUrl: '/ready' });
    const res = createMockRes();
    const next = jest.fn();

    await readyHandler(req, res, next);

    expect(mockPool.query).toHaveBeenCalledWith('SELECT 1');
    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({ status: 'error', db: 'unreachable' });
  });
});
