import assert from 'node:assert/strict';
import { createTaskClock } from './clock.mjs';

// No components, production outputs, logs, or wall-clock sleeps.
let tick = 0;
const now = () => ({ wall: '2026-10-27T00:00:00.000Z', mono: tick });
let clock = createTaskClock(['a', 'b', 'queued'], now);
assert.equal(clock.snapshot().stages[0].status, 'not run');
tick = 1000; clock.dispatch('a');
tick = 2000; clock.dispatch('b');
tick = 4000; clock.settle('b', 'succeeded', true);
assert.throws(() => clock.capture(), /Settle/);
tick = 5000; clock.settle('a', 'succeeded');
tick = 6000;
const result = clock.capture();
assert.equal(result.preparationSeconds, 1);
assert.equal(result.workflowSeconds, 4); // Overlap is not summed.
assert.equal(result.reportingSeconds, 1);
assert.equal(result.totalSeconds, 6);
assert.equal(result.stages[1].durationSeconds, 2);
assert.equal(result.stages[1].cacheReuse, true);
assert.equal(result.stages[2].status, 'not run');
assert.equal(result.stages[2].durationSeconds, null);
assert.throws(() => clock.dispatch('queued'), /captured/);
tick = 7000;
assert.deepEqual(clock.capture(), result);

// Regression: replacing the caller's clock cannot redirect writes to an old run.
const oldClock = clock;
clock = createTaskClock(['a'], now);
tick = 8000; clock.dispatch('a');
tick = 9000; clock.settle('a', 'failed');
assert.equal(clock.snapshot().stages[0].status, 'failed');
assert.deepEqual(oldClock.snapshot(), result);
const detached = clock.snapshot();
detached.stages[0].status = 'corrupted';
assert.equal(clock.snapshot().stages[0].status, 'failed');
assert.throws(() => clock.dispatch('a'), /already dispatched/);
assert.throws(() => clock.dispatch('unknown'), /Unknown stage/);
assert.throws(() => clock.settle('a', 'succeeded'), /not active/);
assert.throws(() => createTaskClock(['a', 'a'], now), /unique/);
const empty = createTaskClock(['a'], now).capture();
assert.equal(empty.workflowSeconds, null);
assert.equal(empty.totalSeconds, 0);
const regressing = createTaskClock(['a'], now);
tick = 0;
assert.throws(() => regressing.dispatch('a'), /regressing/);
console.log('Clock regression checks passed');
