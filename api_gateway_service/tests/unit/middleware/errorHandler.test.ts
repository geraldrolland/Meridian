import { errorHandler } from '../../../src/middleware/errorHandler';
import { createMockReq, createMockRes, createMockNext } from '../../__mocks__/express';

jest.mock('../../../src/middleware/logger', () => ({
  logger: { error: jest.fn() },
}));

describe('Error Handler', () => {
  it('should return 500 with error message', () => {
    const err = new Error('Test error');
    const req = createMockReq();
    const res = createMockRes();
    const next = createMockNext();
    errorHandler(err, req, res, next);
    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({ error: 'Internal gateway error' });
  });
});
