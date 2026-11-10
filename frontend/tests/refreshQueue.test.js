import test from 'node:test';
import assert from 'node:assert/strict';
import { createRefreshQueue } from '../src/refreshQueue.js';

function clock() {
  let timestamp = 0, nextId = 0;
  const timers = new Map();
  return {
    timers,
    options: {
      now: () => timestamp,
      schedule: (fn, delay) => { const id = ++nextId; timers.set(id, { fn, due: timestamp + delay }); return id; },
      cancel: id => timers.delete(id)
    },
    async next() {
      const [id, timer] = [...timers.entries()].sort((a, b) => a[1].due - b[1].due)[0];
      timestamp = timer.due; timers.delete(id); await timer.fn();
    }
  };
}

test('1000 notifications collapse into one pending refresh', async () => {
  const fake = clock(), calls = [];
  const queue = createRefreshQueue(async force => calls.push(force), fake.options);
  for (let n = 0; n < 1000; n++) queue.request();
  assert.equal(fake.timers.size, 1);
  await fake.next();
  assert.deepEqual(calls, [false]);
  assert.equal(fake.timers.size, 0);
});

test('messages during a slow request schedule one trailing refresh without overlap', async () => {
  const fake = clock(), calls = [];
  let finish;
  const queue = createRefreshQueue(force => {
    calls.push(force);
    return new Promise(resolve => { finish = resolve; });
  }, fake.options);
  queue.request();
  const first = fake.next();
  for (let n = 0; n < 1000; n++) queue.request();
  queue.request(true);
  assert.deepEqual(calls, [false]);
  assert.equal(fake.timers.size, 0);
  finish(); await first;
  assert.equal(fake.timers.size, 1);
  assert.equal([...fake.timers.values()][0].due, 1000);
  const second = fake.next();
  assert.deepEqual(calls, [false, true]);
  finish(); await second;
  assert.equal(fake.timers.size, 0);
});

test('unmount cancels scheduled work and ignores late messages', async () => {
  const fake = clock(), calls = [];
  const queue = createRefreshQueue(async () => calls.push('request'), fake.options);
  queue.request(); queue.stop(); queue.request(true);
  assert.equal(fake.timers.size, 0);
  assert.deepEqual(calls, []);
});
