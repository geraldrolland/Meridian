import { requestLogger } from '../../../src/middleware/logger';
import { createMockReq, createMockRes, createMockNext } from '../../__mocks__/express';

describe('Request Logger', () => {
  it('should call next immediately', () => {
    const req = createMockReq({ method: 'GET', originalUrl: '/test', ip: '127.0.0.1' });
    const res = createMockRes();
    const next = createMockNext();
    (res.on as jest.Mock).mockImplementation((event: string, cb: () => void) => {
      if (event === 'finish') cb();
    });
    requestLogger(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it('should register finish event listener', () => {
    const req = createMockReq();
    const res = createMockRes();
    const next = createMockNext();
    requestLogger(req, res, next);
    expect(res.on).toHaveBeenCalledWith('finish', expect.any(Function));
  });
});
