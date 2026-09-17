jest.mock('../../src/config/redis', () => require('../__mocks__/redis').default);

import { runPerformanceTest } from './performance.test';

describe('Performance Tests', () => {
  it.skip('performance test is a standalone script, run via npm run test:perf', () => {
    expect(true).toBe(true);
  });
});
