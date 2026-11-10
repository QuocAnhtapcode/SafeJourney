export const DEFAULT_INCIDENT_FILTERS = Object.freeze({ queue: 'human', owner: 'all', status: 'open' });

export const INCIDENT_QUEUES = [
  { value: 'human', label: 'Cần nhân viên', description: 'Đánh giá khẩn' },
  { value: 'agent', label: 'Agent tự xử lý', description: 'Xác minh tự động' },
  { value: 'all', label: 'Tất cả', description: 'Theo dõi và lịch sử' },
];

// Ownership describes active work only. A history selection must clear it,
// rather than silently returning an impossible combination of filters.
export function updateIncidentFilters(current, patch) {
  const next = { ...current, ...patch };
  if (next.queue !== 'all') next.status = 'open';
  if (next.queue === 'agent' || (patch.status && next.status !== 'open')) next.owner = 'all';
  if (next.owner !== 'all') next.status = 'open';
  return next;
}

export function incidentFilterQuery(filters, page = 0) {
  return new URLSearchParams({
    limit: '100', offset: String(page * 100), assignment: filters.queue,
    owner: filters.owner, status: filters.status,
  }).toString();
}

export function incidentFilterSummary(filters) {
  const queue = INCIDENT_QUEUES.find(item => item.value === filters.queue)?.label || 'Tất cả';
  const status = { open: 'Đang mở', resolved: 'Đã đóng', all: 'Mọi trạng thái' }[filters.status];
  const owner = { all: 'Mọi phân công', unassigned: 'Chưa có người phụ trách', mine: 'Tôi phụ trách' }[filters.owner];
  return `${queue} · ${status}${filters.queue === 'agent' || filters.status !== 'open' ? '' : ` · ${owner}`}`;
}
