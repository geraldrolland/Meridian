import { getUserSession } from '../../../src/middleware/getUserSession';
import { createMockReq, createMockRes, createMockNext } from '../../__mocks__/express';
import { AuthenticatedRequest } from '../../../src/types';

describe('getUserSession middleware', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should set req.user from valid session cookie', async () => {
    const sessionData = { userId: 1, email: 'a@b.com' };
    const cookie = encodeURIComponent(JSON.stringify(sessionData));
    const req = createMockReq({ cookies: { session: cookie } }) as unknown as AuthenticatedRequest;
    const res = createMockRes();
    const next = createMockNext();

    await getUserSession(req, res, next);

    expect(req.user).toEqual(sessionData);
    expect(next).toHaveBeenCalled();
    expect(res.status).not.toHaveBeenCalled();
  });

  it('should call next without setting req.user when cookie is missing', async () => {
    const req = createMockReq({ cookies: {} }) as unknown as AuthenticatedRequest;
    const res = createMockRes();
    const next = createMockNext();

    await getUserSession(req, res, next);

    expect(req.user).toBeUndefined();
    expect(next).toHaveBeenCalled();
    expect(res.status).not.toHaveBeenCalled();
  });

  it('should return 401 when cookie is invalid JSON', async () => {
    const req = createMockReq({ cookies: { session: '%ZZinvalid' } }) as unknown as AuthenticatedRequest;
    const res = createMockRes();
    const next = createMockNext();

    await getUserSession(req, res, next);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Invalid session cookie' });
    expect(next).not.toHaveBeenCalled();
  });
});
