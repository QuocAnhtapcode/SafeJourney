import { api } from './api.js';

export async function apiIncident(id, signal) {
  const row = await api(`/api/incidents/${encodeURIComponent(id)}`, undefined, signal);
  if (!row || Array.isArray(row) || row.id !== id || typeof row.status !== 'string') {
    throw new Error('Máy chủ trả chi tiết sự cố không hợp lệ. Vui lòng làm mới hồ sơ.');
  }
  return row;
}

// Selection belongs to the detail panel, independently of queue/page membership.
export function selectIncidentSnapshot(current, selectedId, incoming) {
  if (!selectedId) return null;
  const previous = current?.id === selectedId ? current : null;
  if (!incoming || incoming.id !== selectedId) return previous;
  if (previous) {
    if (incoming.assignment_version < previous.assignment_version) return previous;
    if (incoming.assignment_version === previous.assignment_version &&
        Date.parse(incoming.server_time) < Date.parse(previous.server_time)) return previous;
  }
  return incoming;
}
