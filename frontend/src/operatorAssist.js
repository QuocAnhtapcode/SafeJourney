// All decisions still carry the owner generation and immutable proposal revision.
export function incidentNow(incident, now) {
  const server = Date.parse(incident?.server_time), received = Number(incident?._receivedAt);
  return Number.isFinite(server) && Number.isFinite(received)
    ? server + Math.max(0, now - received) : now;
}

export function decisionBody(proposal, assignmentVersion, approve) {
  return { proposal_id: proposal.id, assignment_version: assignmentVersion, approve,
    ...(proposal.response_plan ? { proposal_revision: proposal.revision } : {}) };
}

export function reasonBody(options, code, text, assignmentVersion) {
  if (code === 'other') {
    const reason = text.trim();
    return reason.length >= 5 && reason.length <= 500
      ? { assignment_version: assignmentVersion, reason_code: 'other', reason } : null;
  }
  return options.some(option => option.code === code)
    ? { assignment_version: assignmentVersion, reason_code: code } : null;
}

export function followUpStatus(proposal, now) {
  if (proposal?.execution_mode === 'AUTO' || proposal?.status !== 'EXECUTED' || proposal.operator_outcome || !proposal.follow_up_due_at) return null;
  const remaining = new Date(proposal.follow_up_due_at).getTime() - now;
  if (!Number.isFinite(remaining)) return null;
  return remaining <= 0 ? 'Đến lúc xác minh lại kết quả' : `Nhắc xác minh sau ${Math.ceil(remaining / 1000)} giây`;
}

export function automationLabel(incident) {
  if (incident?.status === 'RESOLVED') return 'Hồ sơ đã đóng';
  if (incident?.severity === 3 && incident?.status === 'OPEN') return 'Cần HITL · đánh giá khẩn';
  return { WAITING_RESPONSE: 'Agent đang chờ người nhận xác nhận', MONITORING: 'Đã xác nhận · agent đối chiếu tín hiệu',
    COMPLETE: 'Agent đã hoàn tất playbook', ESCALATED: 'Đã chuyển nhân viên xử lý' }[incident?.automation_state] || 'Đang chuẩn bị xử lý';
}
