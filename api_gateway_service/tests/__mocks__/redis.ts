const mockRedis = {
  get: jest.fn().mockResolvedValue(null),
  set: jest.fn().mockResolvedValue('OK'),
  del: jest.fn().mockResolvedValue(1),
  incr: jest.fn().mockResolvedValue(1),
  expire: jest.fn().mockResolvedValue(1),
  ttl: jest.fn().mockResolvedValue(900),
  eval: jest.fn().mockResolvedValue([1, '9']),
  on: jest.fn(),
  connect: jest.fn().mockResolvedValue(undefined),
};

export default mockRedis;
