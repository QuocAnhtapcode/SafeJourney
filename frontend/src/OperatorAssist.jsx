import React, { useRef, useState } from 'react';
import { decisionBody, reasonBody, followUpStatus } from './operatorAssist.js';

const time = value => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có dữ liệu';

export function ResponsePlan({ incident, proposal, canHandle, canDecide, busy, now, onAction }) {
  const plan = proposal.response_plan;
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState('');
  const [draftRevision, setDraftRevision] = useState(null);
  const followUpRequest = useRef(null);
  const version = incident.assignment_version;
  const expired = new Date(proposal.expires_at).getTime() <= now;
  const reminder = incident.status === 'OPEN' && followUpStatus(proposal, now);
  async function save() {
    const ok = await onAction(`/api/incidents/${incident.id}/proposal-edit`, {
      proposal_id: proposal.id, assignment_version: version, proposal_revision: draftRevision, message: draft.trim(),
    }, 'Đã lưu nội dung mới. Đọc lại bản hiển thị trước khi duyệt.');
    if (ok) setEditing(false);
  }
  function report(outcome) {
    if (followUpRequest.current?.outcome !== outcome) {
      followUpRequest.current = { outcome, request_id: crypto.randomUUID() };
    }
    return onAction(`/api/incidents/${incident.id}/follow-up`, {
      ...followUpRequest.current, proposal_id: proposal.id, assignment_version: version,
    }, 'Đã ghi nhận xác minh và chuẩn bị bước tiếp theo; chưa thực hiện hành động mới.');
  }
  return <div className="proposal">
    <h3>{proposal.execution_mode === 'AUTO' ? 'Playbook agent tự xử lý' : plan ? (proposal.status === 'PENDING' ? 'Gói xử lý khẩn — chờ HITL' : 'Gói xử lý khẩn — đã có quyết định') : 'Đề xuất đang chờ chuẩn bị gói xử lý'}</h3>
    {plan ? <>
      <p><strong>{plan.title}</strong> · MÔ PHỎNG</p>
      <p>Kênh: {plan.action.channel === 'INTERNAL' ? 'Thông báo nội bộ' : plan.action.channel === 'CALL' ? 'Cuộc gọi mô phỏng' : 'SMS mô phỏng'} · Người nhận: <strong>{plan.action.recipient.label}</strong> ({plan.action.recipient.ref})</p>
      <p className="prepared-message">{plan.action.message}</p>
      <p className="notice">{plan.safety_note}</p>
      <p><small>Mẫu nghiệp vụ do backend chuẩn bị · bản {proposal.revision}{plan.operator_edited ? ' · đã được nhân viên chỉnh' : ''}. Kênh liên hệ mô phỏng; việc gửi không được coi là người nhận đã xác nhận.</small></p>
      {proposal.execution_mode === 'AUTO' && <p>Agent tự chạy theo policy. Không cần operator nhận hoặc duyệt bước này.</p>}
      <details><summary>Căn cứ và checklist xác minh</summary>
        <ul>{plan.facts.map((fact, i) => <li key={i}>{fact}</li>)}</ul>
        {plan.missing_evidence.length > 0 && <p>Còn thiếu số đo tại lúc phát hiện; không tự kết luận nguyên nhân.</p>}
        <ul>{plan.checklist.map((check, i) => <li key={i}>{check}</li>)}</ul>
        <p className="proposal-text">{proposal.body}</p>
      </details>
      {canDecide && !editing && <button disabled={busy} onClick={() => {
        setDraft(plan.action.message); setDraftRevision(proposal.revision); setEditing(true);
      }}>Trường hợp đặc biệt: sửa nội dung</button>}
      {editing && <div className="draft-editor">
        <label>Nội dung ngoại lệ<textarea value={draft} onChange={e => setDraft(e.target.value)} maxLength={1500} rows={5}/></label>
        {draftRevision !== proposal.revision && <p className="error">Bản đề xuất đã thay đổi; bản nháp của bạn được giữ lại. Hãy bỏ sửa và mở lại từ bản mới.</p>}
        <button disabled={busy || !canDecide || draftRevision !== proposal.revision || draft.trim().length < 5} onClick={save}>Lưu bản sửa để kiểm tra</button>
        <button disabled={busy} onClick={() => setEditing(false)}>Bỏ sửa</button>
      </div>}
    </> : <>
      <p className="proposal-text">{proposal.body}</p>
      {canDecide && <button disabled={busy} onClick={() => onAction(`/api/incidents/${incident.id}/prepare`, {
        proposal_id: proposal.id, assignment_version: version,
      }, 'Đã chuẩn bị gói xử lý; hãy kiểm tra người nhận và nội dung.')}>Chuẩn bị nội dung và người nhận</button>}
    </>}
    <small>Trạng thái: {proposal.status} · Hết hạn duyệt: {time(proposal.expires_at)}</small>
    {expired && proposal.status === 'PENDING' && <p className="error">Đề xuất đã hết hạn; không thể duyệt.</p>}
    {canHandle && (proposal.status === 'EXPIRED' || (proposal.status === 'PENDING' && expired)) &&
      (proposal.replan_requested_at ? <p role="status">Đã yêu cầu đề xuất mới, vẫn cần kiểm tra và duyệt lại.</p> :
        <button disabled={busy} onClick={() => onAction(`/api/incidents/${incident.id}/replan`, {
          proposal_id: proposal.id, assignment_version: version,
        }, 'Đã yêu cầu đề xuất mới; chưa thực thi.')}>Yêu cầu đề xuất mới</button>)}
    {canDecide && <div className="actions">
      <button className="primary" disabled={busy || editing || !plan} onClick={() => onAction(`/api/incidents/${incident.id}/decision`,
        decisionBody(proposal, version, true), 'Đã duyệt đúng gói đang xem và ghi hành động mô phỏng. Hồ sơ vẫn mở để xác minh kết quả.')}>Duyệt gói xử lý mô phỏng</button>
      <button disabled={busy || editing} onClick={() => onAction(`/api/incidents/${incident.id}/decision`,
        decisionBody(proposal, version, false), 'Đã từ chối đề xuất; hồ sơ vẫn mở.')}>Từ chối</button>
    </div>}
    {reminder && <p role="status"><strong>{reminder}</strong>. {plan?.follow_up}</p>}
    {canHandle && plan && proposal.execution_mode !== 'AUTO' && proposal.status === 'EXECUTED' && !proposal.operator_outcome && <div>
      <p>Chỉ chọn kết quả bạn đã xác minh. Ghi nhận bên dưới sẽ chuẩn bị đề xuất mới để duyệt riêng.</p>
      <div className="actions">
        <button disabled={busy} onClick={() => report('no_response')}>Tôi xác nhận: chưa liên hệ được</button>
        <button disabled={busy} onClick={() => report('needs_help')}>Tôi xác nhận: cần hỗ trợ</button>
      </div>
    </div>}
  </div>;
}

function ReasonAction({ incident, release, busy, onAction }) {
  const options = (release ? incident.release_options : incident.resolution_options) || [];
  const [code, setCode] = useState(''), [text, setText] = useState('');
  const body = reasonBody(options, code, text, incident.assignment_version);
  return <form className="quick-outcome" onSubmit={e => {
    e.preventDefault();
    if (body) void onAction(`/api/incidents/${incident.id}/${release ? 'release' : 'resolve'}`, body,
      release ? 'Đã trả hồ sơ về hàng đợi với lý do được chọn.' : 'Đã đóng sự cố theo xác nhận của bạn và lưu nhật ký.');
  }}>
    <label>{release ? 'Lý do bàn giao' : 'Kết quả đã được bạn xác minh'}
      <select value={code} onChange={e => setCode(e.target.value)} required>
        <option value="">Chọn kết quả phù hợp…</option>
        {options.map(option => <option key={option.code} value={option.code}>{option.label}</option>)}
        <option value="other">Trường hợp đặc biệt — nhập nội dung riêng</option>
      </select>
    </label>
    {code && code !== 'other' && <p>{options.find(option => option.code === code)?.text}</p>}
    {code === 'other' && <label>{release ? 'Nội dung bàn giao đặc biệt' : 'Lý do đóng đặc biệt'}
      <textarea value={text} onChange={e => setText(e.target.value)} required minLength={5} maxLength={500} rows={3}/>
    </label>}
    <button disabled={busy || !body}>{release ? 'Xác nhận trả về hàng đợi' : 'Xác nhận và đóng sự cố'}</button>
  </form>;
}

export function CaseOutcome({ incident, busy, onAction }) {
  return <>
    <h3>Kết thúc hoặc bàn giao — không cần gõ cho trường hợp thường</h3>
    <p>Chọn kết quả thực tế. Agent không tự xác nhận an toàn thay bạn.</p>
    <ReasonAction incident={incident} busy={busy} onAction={onAction}/>
    <details><summary>Bàn giao cho người khác</summary><ReasonAction incident={incident} release busy={busy} onAction={onAction}/></details>
  </>;
}
