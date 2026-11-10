import React, { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, apiList } from './api.js';
import { createRefreshQueue } from './refreshQueue.js';
import { ageSeconds, reconcileTrips, createSosSender } from './journeyData.js';
import { ResponsePlan, CaseOutcome } from './OperatorAssist.jsx';
import { followUpStatus, incidentNow, automationLabel } from './operatorAssist.js';
import { ownershipState } from './incidentOwnership.js';
import { apiIncident, selectIncidentSnapshot } from './incidentSelection.js';
import IncidentFilters from './IncidentFilters.jsx';
import OperationsPanel from './OperationsPanel.jsx';
import { DEFAULT_INCIDENT_FILTERS, incidentFilterQuery, updateIncidentFilters } from './incidentFilters.js';

const LiveMap = lazy(() => import('./LiveMap.jsx'));
const PAGE_SIZE = 50;
const time = value => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có dữ liệu';
const roleNames = { operator: 'Nhân viên an toàn', driver: 'Tài xế', passenger: 'Hành khách' };

class MapBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <p className="error">Chưa tải được phần bản đồ. Bạn vẫn có thể theo dõi danh sách và xử lý sự cố. Tải lại trang để thử bản đồ lần nữa.</p> : this.props.children;
  }
}

export default function App() {
  const [user, setUser] = useState(null), [ready, setReady] = useState(false);
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  const expire = useCallback(() => { setUser(null); setMessage('Phiên đã hết hạn. Vui lòng đăng nhập lại.'); }, []);
  useEffect(() => {
    let active = true;
    api('/api/me').then(u => { if (active) setUser(u); })
      .catch(e => { if (active && e.status !== 401) setMessage(e.message); })
      .finally(() => { if (active) setReady(true); });
    return () => { active = false; };
  }, []);
  async function login(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    const form = new FormData(event.currentTarget);
    try { setUser(await api('/api/login', Object.fromEntries(form))); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  }
  async function logout() {
    setBusy(true);
    try { await api('/api/logout', {}); setUser(null); setMessage('Đã đăng xuất.'); }
    catch (e) { if (e.status === 401) expire(); else setMessage(`Chưa đăng xuất được: ${e.message}`); }
    finally { setBusy(false); }
  }
  if (!ready) return <main>Đang kiểm tra phiên đăng nhập…</main>;
  return <main>
    <header><div><p className="eyebrow">SAFEJOURNEY</p><h1>Giám sát an toàn hành trình</h1></div>
      {user && <div>{user.username} · {roleNames[user.role] || user.role} <button disabled={busy} onClick={logout}>Đăng xuất</button></div>}
    </header>
    <p className="notice">BẢN THỬ NGHIỆM — mọi SMS, cuộc gọi và yêu cầu cứu hộ đều là MÔ PHỎNG. Không kết nối dịch vụ khẩn cấp thực tế.</p>
    {message && <p role="status" className="error">{message}</p>}
    {!user ? <form className="panel login" onSubmit={login}>
      <h2>Đăng nhập</h2>
      <label>Tài khoản<input name="username" autoComplete="username" required/></label>
      <label>Mật khẩu<input name="password" type="password" autoComplete="current-password" required/></label>
      <button disabled={busy}>{busy ? 'Đang đăng nhập…' : 'Đăng nhập'}</button>
    </form> : <Dashboard key={user.id} user={user} onExpire={expire}/>}
  </main>;
}

function Dashboard({ user, onExpire }) {
  const [trips, setTrips] = useState([]), [incidents, setIncidents] = useState([]);
  const [areas, setAreas] = useState([]), [contactRequests, setContactRequests] = useState([]);
  const contactReplies = useRef(new Map());
  const [selected, setSelected] = useState(null), [timeline, setTimeline] = useState([]);
  const [selectedDetail, setSelectedDetail] = useState(null), [detailError, setDetailError] = useState('');
  const [selectedTripId, setSelectedTripId] = useState(null), [selectedTrip, setSelectedTrip] = useState(null);
  const [search, setSearch] = useState(''), [page, setPage] = useState(0);
  const [activeOnly, setActiveOnly] = useState(true);
  const [incidentPage, setIncidentPage] = useState(0);
  const [incidentFilters, setIncidentFilters] = useState(() => user.role === 'operator'
    ? { ...DEFAULT_INCIDENT_FILTERS } : { queue: 'all', owner: 'all', status: 'all' });
  const [incidentLoading, setIncidentLoading] = useState(true), [leaseError, setLeaseError] = useState('');
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [areaError, setAreaError] = useState(''), [timelineError, setTimelineError] = useState('');
  const [now, setNow] = useState(Date.now), [lastTripRefresh, setLastTripRefresh] = useState(null);
  const [connection, setConnection] = useState('Đang kết nối'), [busy, setBusy] = useState(false);
  const [timelineRevision, setTimelineRevision] = useState(0);
  const alive = useRef(true), refreshQueue = useRef(null);
  const actionPending = useRef(false), sendSos = useRef(createSosSender(api));
  const incidentPageRef = useRef(0);
  const selectedRef = useRef(null), incidentListRef = useRef(null);
  const operator = user.role === 'operator';
  const handleError = useCallback(e => {
    if (!alive.current || e.name === 'AbortError') return;
    if (e.status === 401) onExpire(); else setError(e.message);
  }, [onExpire]);
  const refresh = useCallback((force = false) => refreshQueue.current?.request(force), []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    let socket, retryTimer, retries = 0, lastMessage = 0, lastRefresh = 0, lastAreas = 0, areaPending = false;
    let stopped = false;
    async function refreshAreas() {
      if (areaPending) return;
      areaPending = true; lastAreas = Date.now();
      try {
        const rows = await apiList('/api/area-alerts', controller.signal);
        if (!stopped) { setAreas(rows); setAreaError(''); }
      } catch (e) {
        if (!stopped && e.name !== 'AbortError') {
          if (e.status === 401) onExpire(); else setAreaError(e.message);
        }
      }
      finally { areaPending = false; }
    }
    const queue = createRefreshQueue(async force => {
      // Incidents remain realtime. Expensive area clustering has its own cadence.
      if (operator && (force || Date.now() - lastAreas >= 15000)) void refreshAreas();
      const requestedPage = incidentPageRef.current;
      const requestedDetail = operator ? selectedRef.current : null;
      const results = await Promise.allSettled([
        apiList(`/api/trips?include_route=false&active_only=${activeOnly}`, controller.signal),
        apiList(`/api/incidents?${incidentFilterQuery(incidentFilters, requestedPage)}`, controller.signal),
        ...(requestedDetail ? [apiIncident(requestedDetail, controller.signal)] : !operator ? [apiList('/api/contact-requests', controller.signal)] : [])
      ]);
      if (stopped) return;
      if (results[0].status === 'fulfilled') {
        setTrips(previous => reconcileTrips(previous, results[0].value));
        setLastTripRefresh(Date.now());
      }
      if (requestedPage === incidentPageRef.current) {
        setIncidentLoading(false);
        if (results[1].status === 'fulfilled') {
          const receivedAt = Date.now();
          setIncidents(results[1].value.map(row => ({ ...row, _receivedAt: receivedAt })));
        }
      }
      if (requestedDetail && requestedDetail === selectedRef.current) {
        if (results[2].status === 'fulfilled') {
          const row = { ...results[2].value, _receivedAt: Date.now() };
          setSelectedDetail(previous => selectIncidentSnapshot(previous, requestedDetail, row));
          setDetailError('');
        } else {
          const failure = results[2].reason;
          setDetailError('Chưa cập nhật được chi tiết. ' + failure.message);
          if (failure.status === 403 || failure.status === 404) setSelectedDetail(null);
          if (failure.status === 401) handleError(failure);
        }
      }
      if (!operator && results[2]?.status === 'fulfilled') setContactRequests(results[2].value);
      const listResults = !operator ? results : results.slice(0, 2);
      const failed = listResults.find(result => result.status === 'rejected' && result.reason.status === 401)
        || listResults.find(result => result.status === 'rejected');
      if (failed) handleError(failed.reason); else { lastRefresh = Date.now(); setError(''); }
    }, { onError: handleError });
    refreshQueue.current = queue;
    function connect() {
      if (stopped) return;
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
      socket.onopen = async () => {
        try {
          const current = await api('/api/me', undefined, controller.signal);
          if (current.id !== user.id) { if (!stopped) onExpire(); return; }
          if (!stopped) { retries = 0; lastMessage = Date.now(); setConnection('Realtime đang hoạt động'); queue.request(); }
        } catch (e) { handleError(e); }
      };
      socket.onmessage = event => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'refresh' || message.type === 'heartbeat') {
            lastMessage = Date.now();
            if (stopped) return;
            setConnection('Realtime đang hoạt động');
            if (message.type === 'refresh') queue.request();
          }
        } catch { /* Bỏ qua gói không hợp lệ. */ }
      };
      socket.onerror = () => socket.close();
      socket.onclose = event => {
        if (stopped) return;
        if (event.code === 1008) { onExpire(); return; }
        setConnection('Mất WebSocket · cập nhật dự phòng mỗi 5 giây');
        retryTimer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retries++));
      };
    }
    queue.request(true); connect();
    const poll = setInterval(() => {
      const websocketHealthy = socket?.readyState === WebSocket.OPEN && Date.now() - lastMessage < 10000;
      if (!websocketHealthy) setConnection('Kết nối chậm · cập nhật dự phòng mỗi 5 giây');
      // Keep monitoring in background tabs; no visibility pause for safety alerts.
      if (!websocketHealthy || Date.now() - lastRefresh >= 15000) queue.request();
    }, 5000);
    return () => {
      stopped = true; alive.current = false; queue.stop(); controller.abort();
      clearInterval(poll); clearTimeout(retryTimer); socket?.close();
      if (refreshQueue.current === queue) refreshQueue.current = null;
    };
  }, [handleError, operator, onExpire, activeOnly, user.id, incidentFilters]);
  useEffect(() => {
    incidentPageRef.current = incidentPage;
    refresh();
  }, [incidentPage, refresh]);
  useEffect(() => { refresh(); }, [selected, refresh]);
  useEffect(() => { if (incidentListRef.current) incidentListRef.current.scrollTop = 0; }, [incidentPage, incidentFilters]);
  const incident = operator ? (selectedDetail?.id === selected ? selectedDetail : null) : incidents.find(i => i.id === selected);
  const proposal = incident?.proposal;
  const ownership = ownershipState(incident, user.id, now);
  const canHandle = operator && ownership.canHandle && !leaseError && !detailError;
  const incidentVersion = JSON.stringify([incident?.updated_at, incident?.status, incident?.assignment_version, incident?.assigned_operator_id, proposal]);
  useEffect(() => {
    setLeaseError('');
    if (!operator || incident?.status !== 'OPEN' || incident?.assigned_operator_id !== user.id) return;
    let stopped = false, pending = false;
    const controller = new AbortController();
    const id = incident.id, version = incident.assignment_version;
    async function renew() {
      if (stopped || pending || document.visibilityState === 'hidden') return;
      pending = true;
      try {
        await api(`/api/incidents/${id}/lease`, { assignment_version: version }, controller.signal);
        if (!stopped) {
          // Fetch one complete snapshot; don't let a partial lease response overwrite proposal freshness.
          refresh();
          setLeaseError('');
        }
      } catch (e) {
        if (!stopped && e.name !== 'AbortError') {
          setLeaseError('Chưa xác nhận được quyền xử lý. ' + e.message);
          if (e.status === 401) onExpire();
          if (e.status === 409) refresh(true);
        }
      } finally { pending = false; }
    }
    const interval = Math.max(1000, Math.min(60000, (incident.assignment_lease_seconds || 300) * 1000 / 3));
    void renew();
    const timer = setInterval(renew, interval);
    document.addEventListener('visibilitychange', renew);
    return () => { stopped = true; controller.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', renew); };
  }, [operator, incident?.id, incident?.status, incident?.assigned_operator_id, incident?.assignment_version, incident?.assignment_lease_seconds, user.id, onExpire, refresh]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    let pending = false;
    setTimelineError('');
    if (!selected || !operator) { setTimeline([]); return; }
    async function updateTimeline() {
      if (pending) return;
      pending = true;
      try {
        const rows = await apiList(`/api/incidents/${selected}/timeline`, controller.signal);
        if (active) { setTimeline(rows); setTimelineError(''); }
      } catch (e) {
        if (active && e.name !== 'AbortError') {
          if (e.status === 401) onExpire(); else setTimelineError(e.message);
        }
      }
      finally { pending = false; }
    }
    void updateTimeline();
    const timer = setInterval(updateTimeline, 15000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, [selected, incidentVersion, timelineRevision, onExpire, operator]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setSelectedTrip(null);
    if (!selectedTripId) return;
    api(`/api/trips/${encodeURIComponent(selectedTripId)}`, undefined, controller.signal)
      .then(row => { if (active) setSelectedTrip(row); })
      .catch(e => { if (active) handleError(e); });
    return () => { active = false; controller.abort(); };
  }, [selectedTripId, handleError]);
  async function action(path, body, success, request = () => api(path, body)) {
    if (actionPending.current) return;
    actionPending.current = true;
    setBusy(true); setError(''); setNotice('');
    try { await request(); if (alive.current) { setNotice(success); refresh(true); setTimelineRevision(r => r + 1); } return true; }
    catch (e) { handleError(e); if (e.status === 409 && alive.current) refresh(true); return false; }
    finally { actionPending.current = false; if (alive.current) setBusy(false); }
  }
  const filteredTrips = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('vi-VN');
    return query ? trips.filter(t => `${t.id} ${t.label}`.toLocaleLowerCase('vi-VN').includes(query)) : trips;
  }, [trips, search]);
  const pageCount = Math.max(1, Math.ceil(filteredTrips.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleTrips = filteredTrips.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const proposalNow = incidentNow(incident, now);
  const expired = proposal?.expires_at && new Date(proposal.expires_at).getTime() <= proposalNow;
  const canDecide = canHandle && proposal?.execution_mode !== 'AUTO' && proposal?.status === 'PENDING' && !expired;
  function changeIncidentPage(next) {
    incidentPageRef.current = next;
    setIncidentPage(next); setIncidents([]); setIncidentLoading(true);
  }
  function changeIncidentFilters(patch) {
    const next = updateIncidentFilters(incidentFilters, patch);
    if (incidentFilterQuery(next) === incidentFilterQuery(incidentFilters)) return;
    incidentPageRef.current = 0;
    setIncidentPage(0); setIncidents([]); setIncidentLoading(true); setIncidentFilters(next);
  }
  function chooseIncident(row) {
    selectedRef.current = row?.id || null;
    setSelected(row?.id || null); setSelectedDetail(row || null); setDetailError('');
    setTimeline([]); setTimelineRevision(r => r + 1);
  }
  return <>
    <div className="toolbar"><span>{connection}<small className="trip-id">{lastTripRefresh ? `Danh sách vị trí cập nhật ${Math.max(0, Math.floor((now - lastTripRefresh) / 1000))} giây trước` : 'Chưa tải được danh sách vị trí'}</small></span><button onClick={() => { refresh(true); setTimelineRevision(r => r + 1); }}>Làm mới</button></div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success" role="status">{notice}</p>}
    <section className="panel"><h2>Bản đồ hành trình</h2>
      {import.meta.env.VITE_MAPBOX_TOKEN ? <MapBoundary><Suspense fallback={<p>Đang tải bản đồ…</p>}><LiveMap trips={trips} selectedTrip={selectedTrip}/></Suspense></MapBoundary> :
        <p className="empty">Chưa đặt VITE_MAPBOX_TOKEN. Bạn vẫn sử dụng đầy đủ danh sách, SOS và xử lý sự cố bên dưới.</p>}
      <small>Chấm xanh: vị trí nhận trong 30 giây. Chấm vàng: vị trí cuối đã cũ. Không suy đoán vị trí khi mất GPS.</small>
      {selectedTrip && <p>Đang xem tuyến: <strong>{selectedTrip.label}</strong> <button onClick={() => setSelectedTripId(null)}>Bỏ chọn tuyến</button></p>}
    </section>
    {operator && <section className="panel"><h2>Cụm sự cố trong 10 phút</h2><small>Cập nhật khoảng 15 giây một lần; cảnh báo sự cố bên dưới vẫn cập nhật realtime.</small>{areaError && <p className="error" role="alert">Cụm sự cố chưa cập nhật: {areaError}</p>}{areas.length ? areas.map(a => <details key={a.kind + a.cluster_id}><summary>{a.kind}: {a.trip_count} chuyến — nguyên nhân chưa xác minh</summary><p className="cluster-members">{a.trip_ids.join(', ')}</p></details>) : <p>Chưa có cụm từ 2 chuyến trong bán kính lân cận 300 m.</p>}</section>}
    {!operator && <section className="panel"><h2>Yêu cầu xác nhận từ agent — MÔ PHỎNG</h2>
      <p>Chỉ đọc và trả lời khi đã dừng ở nơi an toàn. Không có SMS hoặc cuộc gọi thật được gửi.</p>
      {!contactRequests.length && <p>Chưa có yêu cầu cần phản hồi. Khi cần trợ giúp mới, bạn vẫn có thể bấm SOS ở chuyến đi.</p>}
      {contactRequests.map(request => <article className="proposal" key={request.id}>
        <strong>{request.channel === 'CALL' ? 'Cuộc gọi mô phỏng' : 'Tin nhắn mô phỏng'} · {request.trip_id}</strong>
        <p className="prepared-message">{request.message}</p>
        <div className="actions">{[['safe', 'Tôi đang an toàn'], ['needs_help', 'Tôi cần hỗ trợ']].map(([outcome, label]) => <button key={outcome} disabled={busy}
          onClick={() => {
            const key = request.id + ':' + outcome;
            if (!contactReplies.current.has(key)) contactReplies.current.set(key, crypto.randomUUID());
            void action(`/api/contact-requests/${request.id}/reply`, { request_id: contactReplies.current.get(key), outcome },
              outcome === 'safe' ? 'Đã nhận xác nhận; agent tiếp tục đối chiếu tín hiệu trước khi kết thúc.' : 'Đã chuyển yêu cầu hỗ trợ sang nhân viên an toàn.');
          }}>{label}</button>)}</div>
      </article>)}
    </section>}
    <section className="panel"><h2>Chuyến đi được phép xem ({trips.length})</h2>
      <label>Phạm vi danh sách và bản đồ <select value={activeOnly ? 'active' : 'all'} onChange={e => { setActiveOnly(e.target.value === 'active'); setPage(0); setSelectedTripId(null); }}><option value="active">Chuyến đang hoạt động</option><option value="all">Tất cả chuyến được cấp quyền</option></select></label>
      <div className="toolbar"><label className="trip-search">Tìm chuyến theo mã hoặc tên<input type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} placeholder="Ví dụ: trip-001"/></label>
        <span>{filteredTrips.length} chuyến phù hợp · tối đa {PAGE_SIZE} dòng mỗi trang</span></div>
      <div className="table-scroll"><table><thead><tr><th>Chuyến</th><th>Trạng thái</th><th>Vị trí cuối</th><th>Độ mới GPS</th><th>Thao tác</th></tr></thead>
        <tbody>{visibleTrips.map(t => <tr key={t.id}><td>{t.label}<small className="trip-id">{t.id}</small></td><td>{t.status}</td>
          <td>{t.last_lat == null || t.last_lon == null ? 'Chưa có GPS' : `${Number(t.last_lat).toFixed(5)}, ${Number(t.last_lon).toFixed(5)}`}</td>
          <td>{ageSeconds(t.last_seen, now) === null ? 'Chưa nhận tín hiệu' : `${ageSeconds(t.last_seen, now)} giây trước`}</td>
          <td><button aria-pressed={selectedTripId === t.id} onClick={() => setSelectedTripId(t.id)}>Xem tuyến</button>{!operator && <button className="danger" disabled={busy || t.status !== 'ACTIVE'} onClick={() => action(null, null, 'Máy chủ đã nhận SOS mô phỏng; chưa có nghĩa nhân viên đã tiếp nhận.', () => sendSos.current(t.id))}>SOS mô phỏng</button>}</td>
        </tr>)}</tbody></table></div>{!trips.length && <p>Chưa có chuyến trong phạm vi đã chọn.</p>}
      {trips.length > 0 && !filteredTrips.length && <p>Không có chuyến khớp từ khóa.</p>}
      <nav className="pagination" aria-label="Phân trang chuyến đi"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Trang trước</button>
        <span>Trang {currentPage + 1} / {pageCount}</span><button disabled={currentPage >= pageCount - 1} onClick={() => setPage(currentPage + 1)}>Trang sau</button></nav>
    </section>
    <div className="columns"><section className="panel"><h2>Sự cố · trang {incidentPage + 1}</h2>
      {operator && <IncidentFilters value={incidentFilters} onChange={changeIncidentFilters}/>}
      <small>{incidentLoading ? 'Đang tải hồ sơ…' : `${incidents.length} hồ sơ trên trang này · ưu tiên hồ sơ đang mở, mức độ cao.`}</small>
      {incidentPage > 0 && <p className="notice">Cảnh báo mới có thể nằm ở trang đầu. <button onClick={() => changeIncidentPage(0)}>Về trang đầu</button></p>}
      <div className="incident-list" ref={incidentListRef} role="region" aria-label="Danh sách sự cố" tabIndex={0}>
      {!incidents.length && <p>{incidentLoading ? 'Đang tải danh sách sự cố…' : 'Không có hồ sơ phù hợp với bộ lọc ở trang này.'}</p>}
      {incidents.map(i => <button key={i.id} className={`incident ${selected === i.id ? 'selected' : ''}`} onClick={() => chooseIncident(i)}>
        <strong>{i.kind} · {i.severity}</strong>{operator && i.status === 'OPEN' && <span className="queue-step">{automationLabel(i)}</span>}<span>Chuyến: {i.trip_id}</span><span>{i.status} · {time(i.created_at)}</span><span>{i.summary}</span>
        {operator && <span>{ownershipState(i, user.id, now).active ? `Phụ trách: ${i.assigned_operator_username || i.assigned_operator_id}` : 'Chưa có người phụ trách còn hiệu lực'}</span>}
      </button>)}
      </div>
      <nav className="pagination" aria-label="Phân trang sự cố"><button disabled={incidentPage === 0} onClick={() => changeIncidentPage(incidentPage - 1)}>Trang trước</button>
        <span>Trang {incidentPage + 1}</span><button disabled={incidentLoading || incidents.length < 100} onClick={() => changeIncidentPage(incidentPage + 1)}>Trang sau</button></nav>
    </section><section className="panel"><div className="toolbar"><h2>Chi tiết và phản ứng</h2>{selected && <button onClick={() => chooseIncident(null)}>Bỏ chọn hồ sơ</button>}</div>
      {detailError && <p className="error" role="alert">{detailError} Thao tác được tạm khóa cho tới khi cập nhật lại.</p>}
      {!incident ? <p>{selected ? 'Đang tải hoặc chưa đọc được hồ sơ đã chọn.' : 'Chọn một sự cố để xem bằng chứng và nhật ký.'}</p> : <>
        {operator && !incidents.some(row => row.id === selected) && <p className="notice">Hồ sơ đang xem nằm ngoài hàng đợi hoặc trang danh sách hiện tại. Bạn vẫn có thể tiếp tục xử lý tại đây.</p>}
        <p><b>{incident.kind} · {incident.severity}</b> — {incident.summary}</p><p className="queue-step">{automationLabel(incident)}</p>
        {operator && incident.status === 'OPEN' && <>
          <p>{ownership.active ? `Người phụ trách: ${incident.assigned_operator_username || incident.assigned_operator_id} · còn ${Math.ceil(ownership.remaining / 1000)} giây` : incident.severity === 3 ? 'Hồ sơ khẩn đang chờ người nhận xử lý.' : 'Agent xử lý chính; chỉ nhận nếu cần can thiệp ngoại lệ.'}</p>
          {ownership.canClaim && <button disabled={busy || Boolean(detailError)} onClick={() => action(`/api/incidents/${incident.id}/ack`, {}, 'Đã nhận quyền xử lý hồ sơ.')}>{incident.severity < 3 ? 'Can thiệp ngoại lệ' : 'Nhận xử lý khẩn'}</button>}
          {!ownership.mine && <p className="notice">{ownership.active ? 'Nhân viên khác đang phụ trách; bạn có thể xem hồ sơ.' : incident.severity === 3 ? 'Nhận hồ sơ khẩn để duyệt phương án.' : 'Bạn không cần duyệt bước tự động. Can thiệp ngoại lệ sẽ dừng agent và chuyển hồ sơ sang HITL.'}</p>}
          {leaseError && <p className="error" role="alert">{leaseError}</p>}
        </>}
        <details><summary>Bằng chứng phát hiện</summary><pre>{JSON.stringify(incident.evidence, null, 2)}</pre></details>
        {proposal ? <ResponsePlan key={proposal.id} incident={incident} proposal={proposal} canHandle={canHandle} canDecide={canDecide} busy={busy} now={proposalNow} onAction={action}/> : <p>Agent đang chuẩn bị gói xử lý. Bạn có thể nhận hồ sơ và xem bằng chứng trước.</p>}
        {canHandle && <CaseOutcome key={incident.id + ':' + ownership.version} incident={incident} busy={busy} onAction={action}/>}
        <h3>Nhật ký sự cố</h3>{timelineError && <p className="error" role="alert">Nhật ký chưa cập nhật: {timelineError}</p>}<ol className="timeline">{timeline.map(t => <li key={t.id}><small>{time(t.created_at)} · {t.kind}</small><p>{typeof t.body === 'string' ? t.body : JSON.stringify(t.body)}</p></li>)}</ol>
        {!timeline.length && <p>Chưa có nhật ký hoặc đang tải.</p>}
      </>}
    </section></div>
    <OperationsPanel user={user} trips={trips} onSessionExpired={onExpire}/>
  </>;
}
