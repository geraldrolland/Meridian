import { runLoadTest } from './load.test';

async function main() {
  console.log('Starting Load Tests...');
  await runLoadTest();
  console.log('\nLoad Tests Complete.');
}

main();
