import { runPerformanceTest } from './performance.test';

async function main() {
  console.log('Starting Performance Tests...');
  await runPerformanceTest();
  console.log('\nPerformance Tests Complete.');
}

main();
