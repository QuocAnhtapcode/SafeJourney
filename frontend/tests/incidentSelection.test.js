import test from 'node:test';
import assert from 'node:assert/strict';
import { apiIncident, selectIncidentSnapshot } from '../src/incidentSelection.js';

const before = { id: 'case-1', status: 'OPEN', assignment_version: 0, server_time: '2026-11-01T00:00:00Z' };
const claimed = { ...before, assignment_version: 1, assigned_operator_id: 'operator', server_time: '2026-11-01T00:01:00Z' };

test('detail remains selected after the case leaves the current queue', () => {
  const current = selectIncidentSnapshot(before, before.id, claimed);
  assert.equal(current.assigned_operator_id, 'operator');
  assert.equal(selectIncidentSnapshot(current, before.id, undefined), current);
});
test('late response for another selection cannot replace the open case', () => {
  assert.equal(selectIncidentSnapshot(claimed, 'case-2', before), null);
  const other = { ...before, id: 'case-2' };
  assert.equal(selectIncidentSnapshot(other, 'case-2', claimed), other);
  assert.equal(selectIncidentSnapshot(other, null, claimed), null);
});
test('stale ownership or response time cannot roll the selected case backwards', () => {
  assert.equal(selectIncidentSnapshot(claimed, before.id, before), claimed);
  const delayed = { ...claimed, server_time: before.server_time };
  assert.equal(selectIncidentSnapshot(claimed, before.id, delayed), claimed);
});
test('handoff and resolution refresh the pinned case instead of keeping a frozen copy', () => {
  const transferred = { ...claimed, assignment_version: 3, assigned_operator_id: 'operator2' };
  assert.equal(selectIncidentSnapshot(claimed, before.id, transferred), transferred);
  const resolved = { ...transferred, assignment_version: 4, assigned_operator_id: null, status: 'RESOLVED' };
  assert.equal(selectIncidentSnapshot(transferred, before.id, resolved), resolved);
});
test('detail API rejects malformed data or a different incident', async t => {
  for (const value of [null, [], { ...before, id: 'other' }, { id: before.id }]) {
    t.mock.method(globalThis, 'fetch', async () => Response.json(value));
    await assert.rejects(apiIncident(before.id), /chi tiết sự cố không hợp lệ/);
  }
});
test('detail API returns the requested incident', async t => {
  t.mock.method(globalThis, 'fetch', async path => {
    assert.equal(path, '/api/incidents/case-1');
    return Response.json(claimed);
  });
  assert.deepEqual(await apiIncident(before.id), claimed);
});
