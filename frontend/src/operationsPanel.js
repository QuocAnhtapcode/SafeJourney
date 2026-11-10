import { api, apiList } from './api.js';

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function validatePlan(value, tripId, planId, scenarioId) {
  if (!object(value) || typeof value.id !== 'string' || !value.id || value.trip_id !== tripId
      || (planId && value.id !== planId) || (scenarioId && value.scenario_id !== scenarioId)) {
    throw new Error('Máy chủ trả hồ sơ vận hành không đúng chuyến. Hãy tải lại kết quả.');
  }
  if (value.status === 'RUNNING') throw new Error('Lượt phân tích này còn đang chạy. Chờ hoàn tất rồi làm mới lịch sử.');
  if (value.status === 'FAILED') throw new Error('Lượt phân tích này chưa hoàn tất. Chọn kịch bản tương ứng để kiểm tra lại.');
  if (!object(value.report)) throw new Error('Hồ sơ chưa có kết quả tính toán hợp lệ. Hãy tải lại kết quả.');
  return value;
}

export async function loadScenarios(signal) {
  const rows = await apiList('/api/operations/scenarios', signal);
  if (rows.some(row => !object(row) || typeof row.id !== 'string' || !row.id
      || typeof row.label !== 'string') || new Set(rows.map(row => row.id)).size !== rows.length) {
    throw new Error('Danh sách kịch bản vận hành không hợp lệ. Hãy thử tải lại.');
  }
  return rows;
}

export async function loadPlanHistory(tripId, signal) {
  const rows = await apiList(`/api/operations/plans?trip_id=${encodeURIComponent(tripId)}&limit=10`, signal);
  if (rows.some(row => !object(row) || typeof row.id !== 'string' || row.trip_id !== tripId)) {
    throw new Error('Lịch sử vận hành không đúng chuyến đang chọn. Hãy tải lại.');
  }
  return rows;
}

export async function loadPlan(planId, tripId, signal) {
  return validatePlan(await api(`/api/operations/plans/${encodeURIComponent(planId)}`, undefined, signal), tripId, planId);
}

// One UUID belongs to one immutable input pair until the server confirms it.
// Switching away and back must not turn a lost response into a second plan.
export function createPlanRequests(makeId = () => crypto.randomUUID()) {
  const pending = new Map();
  return {
    forInputs(tripId, scenarioId) {
      const key = JSON.stringify([tripId, scenarioId]);
      if (!pending.has(key)) pending.set(key, {
        trip_id: tripId, scenario_id: scenarioId, request_id: makeId(),
      });
      return { ...pending.get(key) };
    },
    confirmed(body) {
      const key = JSON.stringify([body.trip_id, body.scenario_id]);
      if (pending.get(key)?.request_id === body.request_id) pending.delete(key);
    },
    clear() { pending.clear(); },
  };
}

// Tokens also fence switching A -> B -> A: an old A response is still stale.
export function createPlanSelection() {
  let revision = 0;
  return {
    next() { return ++revision; },
    isCurrent(token) { return token === revision; },
    cancel() { revision += 1; },
  };
}

export function planStatusLabel(status) {
  return { COMPLETED: 'Đã hoàn tất tính toán', PARTIAL: 'Còn điều kiện cần kiểm tra', BLOCKED: 'Chưa đủ điều kiện',
    RUNNING: 'Đang phân tích', FAILED: 'Chưa hoàn tất phân tích' }[status] || 'Chưa xác định trạng thái';
}

const UNASSIGNED_REASONS = {
  vehicle_unavailable: 'Xe không sẵn sàng',
  unreachable: 'Chưa có tuyến tới điểm đón hợp lệ hoặc tuyến đang bị chặn',
  insufficient_seats: 'Không đủ chỗ cho số hành khách yêu cầu',
  pickup_wait_exceeded: 'Thời gian tới điểm đón vượt giới hạn chờ',
  insufficient_energy_reserve: 'Không đủ pin cho cả đoạn đón khách và chuyến đi sau khi giữ dự trữ',
  assignment_capacity_unavailable: 'Xe phù hợp đã được phân cho yêu cầu khác trong lượt này',
  no_vehicles: 'Chưa có xe để phân bổ',
  solver_failed: 'Công cụ tối ưu chưa tìm được kết quả hợp lệ',
};

export function unservedReasonLabels(item) {
  const codes = Array.isArray(item?.reasons) ? item.reasons : [];
  const labels = [...new Set(codes.filter(code => typeof code === 'string').map(code =>
    UNASSIGNED_REASONS[code] || 'Còn ràng buộc chưa được mô tả đầy đủ'))];
  return labels.length ? labels : ['Chưa có xe thỏa ràng buộc'];
}

const FARE_COMPONENTS = [
  ['base', 'Phí mở đầu'], ['distance', 'Theo quãng đường'], ['travel_time', 'Theo thời gian di chuyển'],
  ['waiting_time', 'Thời gian chờ bổ sung'], ['surcharge', 'Phụ phí'], ['discount_applied', 'Giảm giá được trừ'],
];

export function fareBreakdownRows(breakdown) {
  if (!object(breakdown)) return [];
  return FARE_COMPONENTS.filter(([key]) => typeof breakdown[key] === 'string' || typeof breakdown[key] === 'number')
    .map(([key, label]) => ({ key, label, value: breakdown[key], subtract: key === 'discount_applied' }));
}
