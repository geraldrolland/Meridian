import type { Request, Response } from 'express';

export function createMockReq(overrides: Partial<Request> = {}): Request {
  return {
    path: '/',
    url: '/',
    method: 'GET',
    headers: {},
    ip: '127.0.0.1',
    socket: { remoteAddress: '127.0.0.1' },
    cookies: {},
    originalUrl: '/',
    get: jest.fn().mockReturnValue(''),
    ...overrides,
  } as unknown as Request;
}

export function createMockRes(): Response {
  const res = {
    statusCode: 200,
    headers: {} as Record<string, string | number>,
    body: null as unknown,
    cookie: jest.fn(),
    setHeader: jest.fn().mockImplementation((key: string, value: string | number) => {
      res.headers[key] = value;
    }),
    status: jest.fn().mockReturnThis(),
    json: jest.fn().mockImplementation((data: unknown) => {
      res.body = data;
      return res;
    }),
    end: jest.fn().mockReturnThis(),
    on: jest.fn(),
  };
  return res as unknown as Response;
}

export function createMockNext(): jest.Mock {
  return jest.fn();
}
