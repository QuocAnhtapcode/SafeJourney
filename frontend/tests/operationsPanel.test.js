import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlanRequests, createPlanSelection, fareBreakdownRows, planStatusLabel, unservedReasonLabels, validatePlan } from '../src/operationsPanel.js';

test('lost plan responses retain the UUID for retry, including switching away and back', () => {
  let next = 0;
  const requests = createPlanRequests(() => `request-${++next}`);
  const first = requests.forInputs('trip-a', 'rush_hour');
  assert.deepEqual(requests.forInputs('trip-a', 'rush_hour'), first);
  assert.notEqual(requests.forInputs('trip-b', 'rush_hour').request_id, first.request_id);
  assert.notEqual(requests.forInputs('trip-a', 'rain').request_id, first.request_id);
  assert.deepEqual(requests.forInputs('trip-a', 'rush_hour'), first);
  requests.confirmed(first);
  assert.notEqual(requests.forInputs('trip-a', 'rush_hour').request_id, first.request_id);
});

test('an old acknowledgement cannot clear a newer request for the same inputs', () => {
  let next = 0;
  const requests = createPlanRequests(() => `request-${++next}`);
  const old = requests.forInputs('trip', 'normal');
  requests.confirmed(old);
  const newer = requests.forInputs('trip', 'normal');
  requests.confirmed(old);
  assert.deepEqual(requests.forInputs('trip', 'normal'), newer);
});

test('a completed history response confirms a request whose POST response was lost', () => {
  let next = 0;
  const requests = createPlanRequests(() => `request-${++next}`);
  const body = requests.forInputs('trip-a', 'normal');
  const history = validatePlan({ id: body.request_id, trip_id: body.trip_id, scenario_id: body.scenario_id,
    status: 'PARTIAL', report: { advisory_only: true } }, 'trip-a', body.request_id);
  requests.confirmed({ trip_id: history.trip_id, scenario_id: history.scenario_id, request_id: history.id });
  assert.notEqual(requests.forInputs('trip-a', 'normal').request_id, body.request_id);
});

test('changing selection or unmount invalidates outstanding reads and writes', () => {
  const selection = createPlanSelection();
  const oldA = selection.next();
  selection.cancel();
  const b = selection.next();
  selection.cancel();
  const newA = selection.next();
  assert.equal(selection.isCurrent(oldA), false);
  assert.equal(selection.isCurrent(b), false);
  assert.equal(selection.isCurrent(newA), true);
  selection.cancel();
  assert.equal(selection.isCurrent(newA), false);
});

test('plan responses must belong to the selected trip and requested history entry', () => {
  const plan = { id: 'plan-a', trip_id: 'trip-a', scenario_id: 'normal', report: { summary: 'Synthetic test' } };
  assert.equal(validatePlan(plan, 'trip-a', 'plan-a'), plan);
  assert.throws(() => validatePlan(plan, 'trip-b'));
  assert.throws(() => validatePlan(plan, 'trip-a', 'plan-b'));
  assert.throws(() => validatePlan(plan, 'trip-a', undefined, 'rain'));
  assert.throws(() => validatePlan({ ...plan, report: [] }, 'trip-a'));
  assert.throws(() => validatePlan(null, 'trip-a'));
});

test('unfinished history cannot be presented as a completed assessment', () => {
  const plan = { id: 'plan', trip_id: 'trip', report: null };
  assert.match(planStatusLabel('RUNNING'), /Đang phân tích/);
  assert.match(planStatusLabel('FAILED'), /Chưa hoàn tất/);
  assert.throws(() => validatePlan({ ...plan, status: 'RUNNING' }, 'trip'), /còn đang chạy/);
  assert.throws(() => validatePlan({ ...plan, status: 'FAILED' }, 'trip'), /chưa hoàn tất/);
});

test('unserved explanations retain each distinct operational constraint', () => {
  const labels = unservedReasonLabels({ reasons: ['insufficient_energy_reserve', 'pickup_wait_exceeded', 'insufficient_energy_reserve'] });
  assert.equal(labels.length, 2);
  assert.match(labels[0], /Không đủ pin/);
  assert.match(labels[1], /vượt giới hạn chờ/);
  assert.match(unservedReasonLabels({ reasons: ['unreachable'] })[0], /hoặc tuyến đang bị chặn/);
  assert.match(unservedReasonLabels({ reasons: ['unknown_constraint'] })[0], /chưa được mô tả/);
});

test('fare display preserves Decimal component strings and identifies the discount as subtraction', () => {
  const rows = fareBreakdownRows({ base: '15000', distance: '12000.123456', discount_applied: '500.250000' });
  assert.equal(rows[1].value, '12000.123456');
  assert.equal(rows[2].subtract, true);
  assert.equal(rows[0].subtract, false);
  assert.deepEqual(fareBreakdownRows(null), []);
});
