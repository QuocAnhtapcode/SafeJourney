import test from 'node:test';
import assert from 'node:assert/strict';
import { ownershipState } from '../src/incidentOwnership.js';

const received = 1_000_000;
const row = { status: 'OPEN', assigned_operator_id: 'operator', assignment_version: 4,
  server_time: '2026-11-01T00:00:00Z', assignment_expires_at: '2026-11-01T00:05:00Z', _receivedAt: received };

test('ownership uses server remaining time despite a different browser clock', () => {
  const state = ownershipState(row, 'operator', received + 60_000);
  assert.equal(state.remaining, 240_000);
  assert.equal(state.canHandle, true);
  assert.equal(state.version, 4);
});
test('another operator can view but cannot handle an active claim', () => {
  const state = ownershipState(row, 'operator2', received);
  assert.equal(state.canHandle, false);
  assert.equal(state.canClaim, false);
});
test('expiry revokes handling and makes the incident claimable', () => {
  const state = ownershipState(row, 'operator', received + 300_000);
  assert.equal(state.canHandle, false);
  assert.equal(state.canClaim, true);
});
test('unassigned and missing snapshots never grant write controls', () => {
  assert.equal(ownershipState({ status: 'OPEN' }, 'operator', received).canClaim, true);
  assert.equal(ownershipState({ ...row, _receivedAt: undefined }, 'operator', received).canHandle, false);
  assert.equal(ownershipState({ ...row, assignment_version: null }, 'operator', received).canHandle, false);
});
test('resolved incidents cannot be claimed or handled', () => {
  const state = ownershipState({ ...row, status: 'RESOLVED' }, 'operator', received);
  assert.equal(state.canClaim, false);
  assert.equal(state.canHandle, false);
});
