jest.mock('../../src/config/redis', () => require('../__mocks__/redis').default);

import { runLoadTest } from './load.test';

describe('Load Tests', () => {
  it.skip('load test is a standalone script, run via npm run test:load', () => {
    expect(true).toBe(true);
  });
});
