// The live list omits route geometry. Preserve unchanged rows/arrays so a
// heartbeat reconciliation does not rebuild and upload 1,000 map features.
export function reconcileTrips(previous, incoming) {
  const byId = new Map(previous.map(row => [row.id, row]));
  const rows = incoming.map(row => {
    const old = byId.get(row.id);
    const keys = Object.keys(row);
    return old && keys.length === Object.keys(old).length && keys.every(key => Object.is(old[key], row[key])) ? old : row;
  });
  return rows.length === previous.length && rows.every((row, i) => row === previous[i]) ? previous : rows;
}

export function timestamp(value) {
  const result = value ? Date.parse(value) : NaN;
  return Number.isFinite(result) ? result : null;
}

export function ageSeconds(value, now) {
  const observed = timestamp(value);
  return observed === null ? null : Math.max(0, Math.floor((now - observed) / 1000));
}

export function positionsGeoJSON(trips) {
  return { type: 'FeatureCollection', features: trips.flatMap(trip => {
    if (trip.last_lat == null || trip.last_lon == null) return [];
    const lat = Number(trip.last_lat), lon = Number(trip.last_lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return [];
    return [{ type: 'Feature', id: trip.id,
      properties: { label: trip.label, observedAt: timestamp(trip.last_seen) ?? 0 },
      geometry: { type: 'Point', coordinates: [lon, lat] } }];
  }) };
}

export function routeGeoJSON(trip) {
  return { type: 'FeatureCollection', features: trip?.route?.type === 'LineString'
    ? [{ type: 'Feature', properties: {}, geometry: trip.route }] : [] };
}

// Reuse the same id after a lost response. A new acknowledged SOS gets a new id.
export function createSosSender(request, makeId = () => crypto.randomUUID()) {
  const pending = new Map();
  return async tripId => {
    const body = pending.get(tripId) || { event_id: makeId() };
    pending.set(tripId, body);
    const result = await request(`/api/trips/${encodeURIComponent(tripId)}/sos`, body);
    if (pending.get(tripId) === body) pending.delete(tripId);
    return result;
  };
}
