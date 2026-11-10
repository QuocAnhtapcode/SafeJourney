import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_INCIDENT_FILTERS, updateIncidentFilters, incidentFilterQuery, incidentFilterSummary } from '../src/incidentFilters.js';

test('queue, ownership and status are combined in the server request before pagination', () => {
  const filters = updateIncidentFilters(DEFAULT_INCIDENT_FILTERS, { owner: 'mine' });
  const query = new URLSearchParams(incidentFilterQuery(filters, 2));
  assert.equal(query.get('assignment'), 'human');
  assert.equal(query.get('owner'), 'mine');
  assert.equal(query.get('status'), 'open');
  assert.equal(query.get('limit'), '100');
  assert.equal(query.get('offset'), '200');
});

test('agent view clears a personal assignment and always requests open cases', () => {
  const filters = updateIncidentFilters({ queue: 'all', owner: 'mine', status: 'open' }, { queue: 'agent' });
  assert.deepEqual(filters, { queue: 'agent', owner: 'all', status: 'open' });
  assert.equal(DEFAULT_INCIDENT_FILTERS.owner, 'all');
});

test('history selection clears active ownership instead of producing an empty mine/resolved combination', () => {
  const current = { queue: 'all', owner: 'mine', status: 'open' };
  for (const status of ['resolved', 'all']) {
    assert.deepEqual(updateIncidentFilters(current, { status }), { queue: 'all', owner: 'all', status });
  }
  assert.deepEqual(updateIncidentFilters({ queue: 'all', owner: 'all', status: 'resolved' }, { owner: 'mine' }), current);
});

test('switching between human and all preserves ownership while restoring operational status', () => {
  const current = { queue: 'human', owner: 'unassigned', status: 'open' };
  assert.deepEqual(updateIncidentFilters(current, { queue: 'all' }), { ...current, queue: 'all' });
  assert.deepEqual(updateIncidentFilters({ queue: 'all', owner: 'all', status: 'resolved' }, { queue: 'human' }), DEFAULT_INCIDENT_FILTERS);
});

test('filter summary distinguishes active agent work from closed history without implying a total count', () => {
  assert.equal(incidentFilterSummary({ queue: 'agent', owner: 'all', status: 'open' }), 'Agent tự xử lý · Đang mở');
  assert.equal(incidentFilterSummary({ queue: 'all', owner: 'all', status: 'resolved' }), 'Tất cả · Đã đóng');
  assert.match(incidentFilterSummary({ queue: 'human', owner: 'mine', status: 'open' }), /Tôi phụ trách/);
});
