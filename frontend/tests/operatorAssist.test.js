import test from 'node:test';
import assert from 'node:assert/strict';
import { decisionBody, reasonBody, followUpStatus, incidentNow, automationLabel } from '../src/operatorAssist.js';

test('resolved and automated cases are never mislabeled as waiting for human approval', () => {
  assert.equal(automationLabel({ status: 'RESOLVED', severity: 3, automation_state: 'ESCALATED' }), 'Hồ sơ đã đóng');
  assert.match(automationLabel({ status: 'OPEN', severity: 2, automation_state: 'WAITING_RESPONSE' }), /Agent đang chờ người nhận/);
});

test('proposal deadlines use server time even when the browser clock is offset', () => {
  const server = Date.parse('2026-11-02T00:00:00Z');
  assert.equal(incidentNow({ server_time: new Date(server).toISOString(), _receivedAt: 5000 }, 8000), server + 3000);
});

test('approval binds the displayed version, legacy proposals remain compatible', () => {
  assert.equal(decisionBody({ id: 'p', revision: 4, response_plan: {} }, 7, true).proposal_revision, 4);
  assert.deepEqual(decisionBody({ id: 'old' }, 7, false), { proposal_id: 'old', assignment_version: 7, approve: false });
});
test('no automatic closure choice and no invented custom reason', () => {
  const options = [{ code: 'verified_safe' }];
  assert.equal(reasonBody(options, '', '', 1), null);
  assert.equal(reasonBody(options, 'fake', '', 1), null);
  assert.equal(reasonBody(options, 'other', '     ', 1), null);
  assert.deepEqual(reasonBody(options, 'verified_safe', 'unused text', 1), { assignment_version: 1, reason_code: 'verified_safe' });
  assert.equal(reasonBody(options, 'other', '  Đã xác minh ngoại lệ  ', 1).reason, 'Đã xác minh ngoại lệ');
});
test('follow-up clock is a reminder, only for executed proposals without a reported outcome', () => {
  const proposal = { status: 'EXECUTED', follow_up_due_at: '2026-11-02T00:02:00Z' };
  assert.match(followUpStatus(proposal, Date.parse('2026-11-02T00:00:00Z')), /120 giây/);
  assert.equal(followUpStatus(proposal, Date.parse('2026-11-02T00:03:00Z')), 'Đến lúc xác minh lại kết quả');
  assert.equal(followUpStatus({ ...proposal, status: 'PENDING' }, Date.now()), null);
  assert.equal(followUpStatus({ ...proposal, operator_outcome: {} }, Date.now()), null);
  assert.equal(followUpStatus({ ...proposal, execution_mode: 'AUTO' }, Date.now()), null);
});
