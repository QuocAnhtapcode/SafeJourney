// Server time plus local elapsed time avoids trusting the browser's clock offset.
export function ownershipState(incident, userId, now) {
  const received = Number(incident?._receivedAt);
  const server = Date.parse(incident?.server_time);
  const expires = Date.parse(incident?.assignment_expires_at);
  const remaining = Number.isFinite(received) && Number.isFinite(server) && Number.isFinite(expires)
    ? Math.max(0, expires - server - Math.max(0, now - received)) : 0;
  const active = Boolean(incident?.assigned_operator_id) && remaining > 0;
  const open = incident?.status === 'OPEN';
  const mine = active && incident.assigned_operator_id === userId;
  const version = incident?.assignment_version;
  return { active, mine, remaining, version,
    canClaim: open && !active,
    canHandle: open && mine && Number.isSafeInteger(version) && version > 0 };
}
