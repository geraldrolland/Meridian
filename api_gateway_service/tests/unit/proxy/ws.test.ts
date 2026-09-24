import { EventEmitter } from 'events';

const mockUpgradeCb = jest.fn();

jest.mock('express', () => ({
  Router: jest.fn(() => ({
    use: jest.fn(),
  })),
}));

jest.mock('../../../src/config', () => ({
  __esModule: true,
  default: {
    proxySecret: 'test-proxy-secret',
    auth: {
      jwtSecret: 'test-jwt-secret',
    },
  },
}));

jest.mock('../../../src/config/redis', () => ({
  __esModule: true,
  default: require('../../__mocks__/redis').default,
}));

jest.mock('../../../src/middleware/logger', () => ({
  logger: {
    info: jest.fn(),
    error: jest.fn(),
  },
}));

jest.mock('jsonwebtoken', () => ({
  __esModule: true,
  default: {
    verify: jest.fn(),
  },
}));

jest.mock('ws', () => {
  const MockWebSocketServer = jest.fn().mockImplementation(function (this: any) {
    this.handleUpgrade = (_req: any, _socket: any, _head: any, cb: any) => {
      mockUpgradeCb(cb);
    };
  });

  const MockWebSocket = jest.fn().mockImplementation(function (this: any) {
    EventEmitter.call(this);
    this.readyState = 1;
    this.send = jest.fn();
    this.close = jest.fn();
  });
  Object.setPrototypeOf(MockWebSocket.prototype, EventEmitter.prototype);
  MockWebSocket.OPEN = 1;
  MockWebSocket.CLOSED = 3;

  return {
    WebSocket: MockWebSocket,
    WebSocketServer: MockWebSocketServer,
  };
});

const jwtMock = require('jsonwebtoken').default as { verify: jest.Mock };
const redisMock = require('../../../src/config/redis').default as { get: jest.Mock };
const loggerMock = require('../../../src/middleware/logger').logger as { info: jest.Mock; error: jest.Mock };
const WS = require('ws').WebSocket as jest.Mock;

let upgradeHandler: (req: any, socket: any, head: any) => void;
let clientWs: any;

function makeReq(path: string, headers: Record<string, string> = {}) {
  return {
    url: path,
    headers: { host: 'localhost:3000', ...headers },
  };
}

function makeSocket() {
  const socket = new EventEmitter() as any;
  socket.destroy = jest.fn();
  return socket;
}

function createMockUpstream() {
  const ws = new EventEmitter() as any;
  ws.send = jest.fn();
  ws.close = jest.fn();
  ws.readyState = 1;
  return ws;
}

beforeAll(() => {
  const server = new EventEmitter() as any;
  server.on = jest.fn((event: string, cb: any) => {
    if (event === 'upgrade') upgradeHandler = cb;
    server.addListener(event, cb);
  });

  const { createWsProxy } = require('../../../src/proxy/ws');
  createWsProxy(server);
});

beforeEach(() => {
  jest.clearAllMocks();
  mockUpgradeCb.mockClear();

  clientWs = new EventEmitter() as any;
  clientWs.send = jest.fn();
  clientWs.close = jest.fn();
  clientWs.readyState = 1;
});

describe('WebSocket Proxy', () => {
  describe('route matching', () => {
    it('should match /ws/video/notification', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/ws/video/notification'), socket, Buffer.alloc(0));
      expect(mockUpgradeCb).toHaveBeenCalled();
    });

    it('should destroy socket for /ws/dashboard/123', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/ws/dashboard/123'), socket, Buffer.alloc(0));
      expect(socket.destroy).toHaveBeenCalled();
      expect(mockUpgradeCb).not.toHaveBeenCalled();
    });

    it('should destroy socket for /ws/video/123 (old path with userId)', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/ws/video/123'), socket, Buffer.alloc(0));
      expect(socket.destroy).toHaveBeenCalled();
      expect(mockUpgradeCb).not.toHaveBeenCalled();
    });

    it('should destroy socket for unknown paths', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/ws/other/path'), socket, Buffer.alloc(0));
      expect(socket.destroy).toHaveBeenCalled();
      expect(mockUpgradeCb).not.toHaveBeenCalled();
    });

    it('should destroy socket for root path', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/'), socket, Buffer.alloc(0));
      expect(socket.destroy).toHaveBeenCalled();
    });
  });

  describe('token authentication', () => {
    it('should close 4001 when no Authorization header', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/ws/video/notification'), socket, Buffer.alloc(0));

      expect(mockUpgradeCb).toHaveBeenCalled();
      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);
      expect(clientWs.close).toHaveBeenCalledWith(4001, 'Missing token');
    });

    it('should close 4001 when Authorization header has no Bearer prefix', () => {
      const socket = makeSocket();
      upgradeHandler(makeReq('/ws/video/notification', { authorization: 'Basic abc' }), socket, Buffer.alloc(0));

      expect(mockUpgradeCb).toHaveBeenCalled();
      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);
      expect(clientWs.close).toHaveBeenCalledWith(4001, 'Missing token');
    });

    it('should close 4001 for invalid JWT', () => {
      jwtMock.verify.mockImplementation(() => { throw new Error('invalid token'); });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer invalid-token' }),
        socket,
        Buffer.alloc(0),
      );

      expect(mockUpgradeCb).toHaveBeenCalled();
      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);
      expect(clientWs.close).toHaveBeenCalledWith(4001, 'Invalid token');
    });

    it('should close 4001 when JWT has no sessionId', () => {
      jwtMock.verify.mockReturnValue({} as any);

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer token-no-session' }),
        socket,
        Buffer.alloc(0),
      );

      expect(mockUpgradeCb).toHaveBeenCalled();
      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);
      expect(clientWs.close).toHaveBeenCalledWith(4001, 'Invalid token payload');
    });

    it('should accept token from query parameter', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-query' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'uq1', email: 'q@q.com' }));

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification?token=query-token'),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      expect(jwtMock.verify).toHaveBeenCalledWith('query-token', 'test-jwt-secret');
      expect(mockUpgradeCb).toHaveBeenCalled();
      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);
      expect(clientWs.close).not.toHaveBeenCalledWith(4001, 'Missing token');
    });
  });

  describe('session lookup', () => {
    it('should close 4001 when session not found in Redis', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-123' } as any);
      redisMock.get.mockResolvedValue(null as any);

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      expect(mockUpgradeCb).toHaveBeenCalled();
      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);
      expect(clientWs.close).toHaveBeenCalledWith(4001, 'Session expired or not found');
    });
  });

  describe('successful connection', () => {
    it('should connect to upstream video-service with proxy signature headers', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-456' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u1', role: 'user', email: 'a@b.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      expect(WS).toHaveBeenCalledWith(
        'ws://video-service:8000/api/video/ws/video/notification',
        expect.objectContaining({
          headers: expect.objectContaining({
            'x-proxy-signature': expect.any(String),
            'x-proxy-timestamp': expect.any(String),
          }),
        }),
      );
    });

    it('should forward the session cookie to upstream video-service', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-cookie' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u-cookie', email: 'c@c.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      expect(WS).toHaveBeenCalledWith(
        'ws://video-service:8000/api/video/ws/video/notification',
        expect.objectContaining({
          headers: expect.objectContaining({
            cookie: 'session=' + encodeURIComponent(JSON.stringify({ userId: 'u-cookie', email: 'c@c.com' })),
          }),
        }),
      );
    });

    it('should log connection on upstream open', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-789' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u2', role: 'admin', email: 'x@y.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      mockUpstream.emit('open');
      expect(loggerMock.info).toHaveBeenCalledWith(
        'WS proxy connected to video-service for user %s', 'u2',
      );
    });
  });

  describe('message proxying', () => {
    it('should forward client messages to upstream', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-msg' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u3', role: 'user', email: 'm@n.com' }));

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      const upstreamWs = WS.mock.instances[WS.mock.instances.length - 1];
      upstreamWs.emit('open');
      clientWs.emit('message', Buffer.from('hello upstream'));
      expect(upstreamWs.send).toHaveBeenCalled();
    });

    it('should forward upstream messages to client', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-msg2' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u4', role: 'user', email: 'p@q.com' }));

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      const upstreamWs = WS.mock.instances[WS.mock.instances.length - 1];
      upstreamWs.emit('open');
      upstreamWs.emit('message', Buffer.from('hello client'));
      expect(clientWs.send).toHaveBeenCalled();
    });

    it('should not send to upstream if upstream is not OPEN', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-msg3' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u5', role: 'user', email: 'r@s.com' }));

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      const upstreamWs = WS.mock.instances[WS.mock.instances.length - 1];
      upstreamWs.readyState = 3;
      upstreamWs.emit('open');
      clientWs.emit('message', Buffer.from('should not send'));
      expect(upstreamWs.send).not.toHaveBeenCalled();
    });
  });

  describe('disconnection handling', () => {
    it('should close upstream when client disconnects', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-disc' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u6', role: 'user', email: 't@u.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      mockUpstream.emit('open');
      clientWs.emit('close');
      expect(mockUpstream.close).toHaveBeenCalled();
      expect(loggerMock.info).toHaveBeenCalledWith(
        'WS proxy client disconnected for user %s', 'u6',
      );
    });

    it('should close client when upstream disconnects', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-disc2' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u7', role: 'user', email: 'v@w.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      mockUpstream.emit('open');
      mockUpstream.emit('close');
      expect(clientWs.close).toHaveBeenCalled();
      expect(loggerMock.info).toHaveBeenCalledWith(
        'WS proxy upstream disconnected for user %s', 'u7',
      );
    });
  });

  describe('error handling', () => {
    it('should close upstream on client error', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-err' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u8', role: 'user', email: 'x@y.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      mockUpstream.emit('open');
      clientWs.emit('error', new Error('client read error'));
      expect(mockUpstream.close).toHaveBeenCalled();
      expect(loggerMock.error).toHaveBeenCalledWith(
        'WS proxy client error for user %s: %s', 'u8', 'client read error',
      );
    });

    it('should close client on upstream error', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-err2' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u9', role: 'user', email: 'z@w.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      mockUpstream.emit('open');
      mockUpstream.emit('error', new Error('upstream read error'));
      expect(clientWs.close).toHaveBeenCalled();
      expect(loggerMock.error).toHaveBeenCalledWith(
        'WS proxy upstream error for user %s: %s', 'u9', 'upstream read error',
      );
    });

    it('should close client with 1011 on upstream connection error', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-err3' } as any);
      redisMock.get.mockResolvedValue(JSON.stringify({ userId: 'u10', role: 'user', email: 'a@b.com' }));

      const mockUpstream = createMockUpstream();
      const WS = require('ws').WebSocket;
      WS.mockImplementation(function (this: any) {
        Object.assign(this, mockUpstream);
        EventEmitter.call(this);
      });

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      const cb = mockUpgradeCb.mock.calls[0][0];
      cb(clientWs);

      mockUpstream.emit('error', new Error('ECONNREFUSED'));
      expect(clientWs.close).toHaveBeenCalledWith(1011, 'Backend unavailable');
      expect(loggerMock.error).toHaveBeenCalledWith(
        'WS proxy upstream connection error: %s', 'ECONNREFUSED',
      );
    });

    it('should destroy socket on Redis error', async () => {
      jwtMock.verify.mockReturnValue({ sessionId: 'sess-redis-err' } as any);
      redisMock.get.mockRejectedValue(new Error('Redis connection lost'));

      const socket = makeSocket();
      upgradeHandler(
        makeReq('/ws/video/notification', { authorization: 'Bearer valid-token' }),
        socket,
        Buffer.alloc(0),
      );

      await new Promise((r) => setTimeout(r, 10));

      expect(socket.destroy).toHaveBeenCalled();
      expect(loggerMock.error).toHaveBeenCalledWith(
        'WS proxy Redis error: %s', 'Redis connection lost',
      );
    });
  });
});
