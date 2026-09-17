/** @type {import('jest').Config} */
module.exports = {
  transform: {
    '^.+\\.ts$': '@swc/jest',
  },
  transformIgnorePatterns: [
    'node_modules/(?!(express|cookie-parser|cors)/)',
  ],
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  moduleFileExtensions: ['ts', 'js', 'json'],
  clearMocks: true,
  restoreMocks: true,
  testTimeout: 10000,
};
