import React from 'react';
import { DEFAULT_INCIDENT_FILTERS, INCIDENT_QUEUES, incidentFilterSummary } from './incidentFilters.js';

export default function IncidentFilters({ value, onChange }) {
  const agent = value.queue === 'agent';
  const history = value.status !== 'open';
  const defaults = Object.keys(DEFAULT_INCIDENT_FILTERS).every(key => value[key] === DEFAULT_INCIDENT_FILTERS[key]);
  return <div className="incident-filters">
    <div className="filter-heading"><span id="incident-queue-label">Nhóm xử lý</span>
      <button className="filter-reset" disabled={defaults} onClick={() => onChange(DEFAULT_INCIDENT_FILTERS)}>Về mặc định</button>
    </div>
    <div className="queue-segments" role="group" aria-labelledby="incident-queue-label">
      {INCIDENT_QUEUES.map(queue => <button type="button" key={queue.value} className="queue-segment"
        aria-pressed={value.queue === queue.value} onClick={() => onChange({ queue: queue.value })}>
        <strong>{queue.label}</strong><small>{queue.description}</small>
      </button>)}
    </div>
    <div className="queue-refinements">
      <label>Phụ trách<select value={value.owner} disabled={agent || history}
        aria-describedby="incident-filter-help" onChange={e => onChange({ owner: e.target.value })}>
        <option value="all">Không giới hạn</option>
        <option value="unassigned">Chưa có người phụ trách</option>
        <option value="mine">Tôi phụ trách</option>
      </select></label>
      <label>Trạng thái<select value={value.status} disabled={value.queue !== 'all'}
        aria-describedby="incident-filter-help" onChange={e => onChange({ status: e.target.value })}>
        <option value="open">Đang mở</option><option value="resolved">Đã đóng</option><option value="all">Mọi trạng thái</option>
      </select></label>
    </div>
    <p className="filter-help" id="incident-filter-help">{agent
      ? 'Agent theo dõi các hồ sơ đang mở; không cần nhân viên nhận xử lý.'
      : value.queue === 'human' ? 'Hồ sơ khẩn đang mở cần nhân viên đánh giá. Chọn Tất cả để xem lịch sử.'
      : history ? 'Phân công chỉ áp dụng cho hồ sơ đang mở. Lịch sử hiển thị mọi người phụ trách.'
      : 'Kết hợp phụ trách và trạng thái để tìm hồ sơ. Quyền phụ trách hết hạn được tính là chưa có người phụ trách.'}</p>
    <p className="filter-summary" role="status">{incidentFilterSummary(value)}</p>
  </div>;
}
