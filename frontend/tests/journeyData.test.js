import test from 'node:test';
import assert from 'node:assert/strict';
import { reconcileTrips, positionsGeoJSON, routeGeoJSON, ageSeconds, createSosSender } from '../src/journeyData.js';

test('unchanged fleet keeps references while one moving vehicle changes only its row', () => {
  const fleet = Array.from({ length: 1000 }, (_, id) => ({ id: String(id), version: 1, route: null }));
  assert.equal(reconcileTrips(fleet, fleet.map(row => ({ ...row }))), fleet);
  const next = fleet.map(row => ({ ...row }));
  next[500].version++;
  const merged = reconcileTrips(fleet, next);
  assert.equal(merged[499], fleet[499]);
  assert.notEqual(merged[500], fleet[500]);
});

test('GPS age advances without a new response and invalid locations are omitted', () => {
  const observed = '2026-10-24T10:00:00Z';
  assert.equal(ageSeconds(observed, Date.parse(observed) + 45000), 45);
  assert.equal(ageSeconds('invalid', Date.now()), null);
  const trips = [{ id: 'a', last_lat: 10.78, last_lon: 106.7, last_seen: observed },
    { id: 'b', last_lat: null, last_lon: null }, { id: 'c', last_lat: 95, last_lon: 106.7 }];
  assert.deepEqual(positionsGeoJSON(trips).features.map(p => p.id), ['a']);
  assert.equal(routeGeoJSON(null).features.length, 0);
});

test('SOS retries reuse one event id after a lost response, then allocate a new one', async () => {
  const sent = [];
  let attempts = 0, ids = 0;
  const send = createSosSender(async (path, body) => {
    sent.push(body.event_id);
    if (++attempts === 1) throw new Error('lost response after server commit');
    return { status: 'received' };
  }, () => `id-${++ids}`);
  await assert.rejects(send('trip-1'));
  await send('trip-1');
  await send('trip-1');
  assert.deepEqual(sent, ['id-1', 'id-1', 'id-2']);
});
