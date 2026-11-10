import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { createPlanRequests, createPlanSelection, fareBreakdownRows, loadPlan, loadPlanHistory, loadScenarios, planStatusLabel, unservedReasonLabels, validatePlan } from './operationsPanel.js';
import './operations.css';

const number = (value, digits = 1) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
  ? Number(value).toLocaleString('vi-VN', { maximumFractionDigits: digits }) : 'Chưa có';
const money = (value, digits = 0) => value === null || value === undefined || value === '' ? 'Chưa có kết quả' : `${number(value, digits)} ₫`;
const time = value => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có thời điểm';
const strings = value => Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
const sourceLabel = source => ({
  postgis_stored_geometry_with_assumed_speed: 'Tuyến đã lưu, thời gian theo tốc độ giả định',
  osrm_failed_geometry_reference_only: 'Tuyến lưu để tham khảo; dịch vụ định tuyến chưa xác nhận được',
  great_circle_estimate: 'Khoảng cách đường chim bay, chưa xác minh đường bộ',
  osrm: 'Dịch vụ định tuyến đường bộ đã cấu hình',
  synthetic_seasonal_counts_with_explicit_scenario_factor: 'Số liệu nhu cầu mô phỏng và hệ số của kịch bản',
}[source] || 'Chưa xác định nguồn');

function Metric({ label, children }) {
  return <div className="operations-metric"><dt>{label}</dt><dd>{children}</dd></div>;
}

function PlanReport({ plan, scenarioLabel }) {
  const { report } = plan;
  const trace = Array.isArray(report.trace) ? report.trace : [];
  const signals = Array.isArray(report.signals) ? report.signals : [];
  const assignments = Array.isArray(report.allocation?.assignments) ? report.allocation.assignments : [];
  const unserved = Array.isArray(report.allocation?.unserved) ? report.allocation.unserved : [];
  const assumptions = strings(report.assumptions), limitations = strings(report.limitations);
  const { route, fare, refund, battery, charging, demand, allocation } = report;
  const fareRows = fareBreakdownRows(fare?.breakdown);
  return <article className="operations-report" aria-label="Kết quả kiểm tra vận hành">
    <div className="operations-result-heading">
      <div><h3>{planStatusLabel(plan.status)}</h3><p className="operations-note">Kết quả đã lưu · {scenarioLabel || plan.scenario_id}</p></div>
      <small>{time(plan.created_at)}</small>
    </div>
    {typeof report.summary === 'string' && <p className="operations-summary">{report.summary}</p>}
    {signals.length > 0 && <div className="operations-signals" role="status">
      <h4>Điểm cần xác minh</h4>
      <ul>{signals.map((signal, index) => <li key={`${signal.code || 'signal'}-${index}`}>{signal.summary || 'Có dữ liệu cần đối chiếu thêm.'}</li>)}</ul>
      <small>Các dấu hiệu hỗ trợ rà soát, chưa kết luận gian lận hoặc nguyên nhân sự cố.</small>
    </div>}
    <div className="operations-grid">
      <section className="operations-card">
        <h4>Lộ trình</h4>
        {route ? <>
          <p className={route.verified === true ? 'operations-note' : 'operations-caution'}>
            {route.verified === true ? 'Có kết quả tuyến đường từ công cụ định tuyến' : 'Ước lượng; chưa xác nhận tuyến đường thực tế'}
          </p>
          <dl><Metric label="Quãng đường">{number(route.distance_m == null ? null : Number(route.distance_m) / 1000)} km</Metric>
            <Metric label="Thời gian">{number(route.duration_s == null ? null : Number(route.duration_s) / 60)} phút</Metric></dl>
          <small>Nguồn: {sourceLabel(route.source)}</small>
        </> : <p>Chưa có kết quả định tuyến.</p>}
      </section>
      <section className="operations-card">
        <h4>Cước phí và hoàn tiền</h4>
        {fare ? <><dl><Metric label="Cước tính theo chính sách demo">{money(fare.total_vnd)}</Metric>
          <Metric label="Hoàn tiền tính toán">{refund ? money(refund.refund_vnd) : 'Chưa có yêu cầu'}</Metric></dl>
          <small>Chính sách: {fare.policy_version || 'Chưa có phiên bản'} · {fare.currency || 'VND'}</small>
          {fareRows.length > 0 && <details className="operations-fare-details"><summary>Chi tiết cước và phần hoàn</summary>
            <dl className="operations-fare-lines">{fareRows.map(item => <div key={item.key}>
              <dt>{item.label}</dt><dd>{item.subtract ? '− ' : ''}{money(item.value, 6)}</dd>
            </div>)}</dl>
            <p className="operations-note">Tổng cước làm tròn đến 1 đồng sau khi trừ giảm giá.</p>
            {refund?.input && <dl className="operations-fare-lines">
              <div><dt>Đã thu trong kịch bản</dt><dd>{money(refund.input.paid_vnd, 6)}</dd></div>
              <div><dt>Đã hoàn trước đó</dt><dd>{money(refund.input.already_refunded_vnd, 6)}</dd></div>
              <div><dt>Trần còn lại có thể hoàn</dt><dd>{money(refund.remaining_refundable_vnd, 6)}</dd></div>
            </dl>}
          </details>}
        </> : <p>Chưa có kết quả tính cước.</p>}
        <p className="operations-note">Số tiền là kết quả tính toán mô phỏng, không phải giao dịch đã thực hiện.</p>
      </section>
      <section className="operations-card">
        <h4>Pin và trạm sạc</h4>
        {battery ? <>
          <p className={battery.feasible === true ? 'operations-note' : 'operations-caution'}>
            {battery.feasible === true ? 'Đủ năng lượng theo đầu vào và mô hình đang dùng' : battery.feasible === false ? 'Không đủ năng lượng với mức dự trữ yêu cầu' : 'Chưa xác định được khả năng đáp ứng'}
          </p>
          <dl><Metric label="Năng lượng chuyến cần">{number(battery.required_kwh, 2)} kWh</Metric>
            <Metric label="Có thể dùng sau dự trữ">{number(battery.available_kwh, 2)} kWh</Metric>
            <Metric label="Dự trữ tối thiểu">{number(battery.reserve_kwh, 2)} kWh</Metric>
            <Metric label="Còn lại sau chuyến (ước tính)">{number(battery.remaining_kwh, 2)} kWh</Metric></dl>
        </> : <p>Chưa có dữ liệu pin.</p>}
        {charging && <div className="operations-charging">
          {charging.reachable_with_reserve === false && <p className="operations-caution"><strong>Không đủ pin tới trạm và giữ mức dự trữ.</strong> Chưa có phương án tới trạm thỏa ràng buộc.</p>}
          {charging.reachable_with_reserve !== true && charging.reachable_with_reserve !== false && <p className="operations-caution">Chưa xác nhận đủ pin để tới trạm.</p>}
          <p className="operations-note">{charging.reachable_with_reserve === false ? 'Ước lượng sạc dưới đây chỉ có ý nghĩa nếu xe đã được đưa tới trạm.' : 'Thời gian dưới đây tính từ khi tới trạm, chưa bao gồm di chuyển.'}</p>
          <dl className="operations-submetrics">
            <Metric label="Chờ tới lượt sạc">{number(charging.wait_minutes)} phút</Metric>
            <Metric label="Thời gian sạc">{number(charging.charge_minutes)} phút</Metric>
            <Metric label="Tổng chờ và sạc">{number(charging.total_minutes)} phút</Metric>
          </dl>
        </div>}
      </section>
      <section className="operations-card">
        <h4>Cung – cầu khu vực</h4>
        {demand ? <>
          <dl><Metric label="Nhu cầu nền">{number(demand.historical_expected)} chuyến</Metric>
            <Metric label="Nhu cầu theo kịch bản">{number(demand.scenario_expected)} chuyến</Metric>
            <Metric label="Xe trong kịch bản">{number(demand.available_vehicles, 0)}</Metric>
            <Metric label="Chưa đáp ứng sau kiểm tra">{number(Array.isArray(allocation?.unserved) ? allocation.unserved.length : null, 0)}</Metric></dl>
          <small>Nguồn: {sourceLabel(demand.source)}</small>
          {demand.area_id && <p className="operations-area">{demand.cell_system || 'Vùng'}: {demand.area_id}</p>}
        </> : <p>Chưa có kết quả phân tích nhu cầu.</p>}
      </section>
    </div>
    {allocation && <section className="operations-allocation">
      <h4>Phương án phân bổ mô phỏng</h4>
      <p>{assignments.length} yêu cầu được phân bổ · {unserved.length} yêu cầu chưa đáp ứng.</p>
      {assignments.length > 0 && <div className="table-scroll"><table>
        <thead><tr><th>Yêu cầu</th><th>Xe</th><th>Thời gian tới điểm đón</th></tr></thead>
        <tbody>{assignments.slice(0, 10).map((item, index) => <tr key={`${item.request_id}-${index}`}>
          <td>{item.request_id}</td><td>{item.vehicle_id}</td><td>{number(item.pickup_seconds == null ? null : Number(item.pickup_seconds) / 60)} phút</td>
        </tr>)}</tbody>
      </table></div>}
      {assignments.length > 10 && <small>Hiển thị 10 phân bổ đầu trong phương án.</small>}
      {unserved.length > 0 && <details><summary>Yêu cầu chưa đáp ứng</summary><ul>{unserved.slice(0, 30).map((item, index) =>
        <li key={index}>{typeof item === 'string' ? item : <><strong>{item.request_id || 'Yêu cầu'}</strong>: {unservedReasonLabels(item).join('; ')}.</>}</li>)}</ul>
        {unserved.length > 30 && <small>Hiển thị 30 yêu cầu đầu chưa đáp ứng.</small>}
      </details>}
    </section>}
    <details className="operations-details"><summary>Các bước agent và giả định tính toán</summary>
      {trace.length > 0 && <ol className="operations-trace">{trace.map((step, index) => <li key={`${step.agent}-${index}`}>
        <strong>{step.label || step.agent || `Bước ${index + 1}`}</strong>{step.summary && <p>{step.summary}</p>}
      </li>)}</ol>}
      {assumptions.length > 0 && <><h4>Đầu vào và giả định</h4><ul>{assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
      {limitations.length > 0 && <><h4>Giới hạn của kết quả</h4><ul>{limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
    </details>
  </article>;
}

function OperationsWorkspace({ trips, onSessionExpired }) {
  const [scenarios, setScenarios] = useState([]), [scenarioId, setScenarioId] = useState('');
  const [tripId, setTripId] = useState(''), [plan, setPlan] = useState(null), [history, setHistory] = useState([]);
  const [error, setError] = useState(''), [historyError, setHistoryError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(true), [catalogVersion, setCatalogVersion] = useState(0);
  const [historyVersion, setHistoryVersion] = useState(0), [busy, setBusy] = useState(false);
  const alive = useRef(true), busyRef = useRef(false), running = useRef(null);
  const selected = useRef({ tripId: '', scenarioId: '' });
  const requests = useRef(createPlanRequests()), selection = useRef(createPlanSelection());
  const expireRef = useRef(onSessionExpired); expireRef.current = onSessionExpired;
  const fail = useCallback(e => {
    if (!alive.current || e.name === 'AbortError') return;
    if (e.status === 401) expireRef.current?.(); else setError(e.message);
  }, []);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; selection.current.cancel(); running.current?.abort(); requests.current.clear(); };
  }, []);
  const changeSelection = useCallback((nextTrip, nextScenario) => {
    selection.current.cancel(); running.current?.abort(); running.current = null;
    busyRef.current = false; setBusy(false); setPlan(null); setError('');
    selected.current = { tripId: nextTrip, scenarioId: nextScenario };
    setTripId(nextTrip); setScenarioId(nextScenario);
  }, []);
  useEffect(() => {
    if (!trips.some(trip => trip.id === selected.current.tripId)) {
      changeSelection(trips[0]?.id || '', selected.current.scenarioId);
    }
  }, [trips, changeSelection]);
  useEffect(() => {
    const controller = new AbortController();
    setCatalogLoading(true);
    loadScenarios(controller.signal).then(rows => {
      if (controller.signal.aborted) return;
      setScenarios(rows);
      const next = rows.some(row => row.id === selected.current.scenarioId) ? selected.current.scenarioId : rows[0]?.id || '';
      changeSelection(selected.current.tripId, next);
    }).catch(fail).finally(() => { if (!controller.signal.aborted) setCatalogLoading(false); });
    return () => controller.abort();
  }, [catalogVersion, changeSelection, fail]);
  useEffect(() => {
    const controller = new AbortController();
    setHistory([]); setHistoryError(''); setHistoryLoading(Boolean(tripId));
    if (tripId) loadPlanHistory(tripId, controller.signal).then(rows => {
      if (!controller.signal.aborted) setHistory(rows);
    }).catch(e => {
      if (controller.signal.aborted || e.name === 'AbortError') return;
      if (e.status === 401) expireRef.current?.(); else setHistoryError(e.message);
    }).finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [tripId, historyVersion]);

  async function run(event) {
    event.preventDefault();
    if (busyRef.current || !tripId || !scenarioId) return;
    const body = requests.current.forInputs(tripId, scenarioId);
    const token = selection.current.next(), controller = new AbortController();
    running.current?.abort(); running.current = controller;
    busyRef.current = true; setBusy(true); setError(''); setPlan(null);
    try {
      const result = validatePlan(await api('/api/operations/plans', body, controller.signal), body.trip_id, body.request_id, body.scenario_id);
      if (!alive.current || !selection.current.isCurrent(token)) return;
      requests.current.confirmed(body); setPlan(result); setHistoryVersion(value => value + 1);
    } catch (e) { if (selection.current.isCurrent(token)) fail(e); }
    finally {
      if (alive.current && selection.current.isCurrent(token)) { busyRef.current = false; setBusy(false); }
    }
  }

  async function openHistory(id) {
    if (busyRef.current) return;
    const token = selection.current.next(), controller = new AbortController();
    running.current?.abort(); running.current = controller;
    busyRef.current = true; setBusy(true); setError(''); setPlan(null);
    try {
      const result = await loadPlan(id, tripId, controller.signal);
      if (alive.current && selection.current.isCurrent(token)) {
        requests.current.confirmed({ trip_id: result.trip_id, scenario_id: result.scenario_id, request_id: result.id });
        setPlan(result);
      }
    } catch (e) { if (selection.current.isCurrent(token)) fail(e); }
    finally {
      if (alive.current && selection.current.isCurrent(token)) { busyRef.current = false; setBusy(false); }
    }
  }

  const scenario = scenarios.find(item => item.id === scenarioId);
  return <section className="panel operations-panel" aria-labelledby="operations-title">
    <div className="operations-heading"><div><h2 id="operations-title">Agent kiểm tra vận hành</h2>
      <p>Chọn kịch bản để đối chiếu lộ trình, chi phí, pin và phương án phân bổ bằng công cụ tính toán.</p></div>
      <span className="operations-badge">MÔ PHỎNG</span></div>
    <p className="operations-note">Các phương án dùng dữ liệu và giả định của kịch bản. Hồ sơ khẩn tiếp tục theo quy trình HITL ở khu vực sự cố.</p>
    <form className="operations-controls" onSubmit={run}>
      <label>Chuyến cần kiểm tra<select value={tripId} onChange={e => changeSelection(e.target.value, scenarioId)}>
        {!trips.length && <option value="">Chưa có chuyến được phép xem</option>}
        {trips.map(trip => <option key={trip.id} value={trip.id}>{trip.label || trip.id}{trip.label && trip.label !== trip.id ? ` · ${trip.id}` : ''}</option>)}
      </select></label>
      <label>Kịch bản<select value={scenarioId} disabled={catalogLoading || !scenarios.length} onChange={e => changeSelection(tripId, e.target.value)}>
        {!scenarios.length && <option value="">{catalogLoading ? 'Đang tải kịch bản…' : 'Chưa tải được kịch bản'}</option>}
        {scenarios.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      <button className="primary" disabled={busy || catalogLoading || !tripId || !scenarioId}>{busy ? 'Đang tính toán…' : 'Agent kiểm tra vận hành'}</button>
    </form>
    {scenario?.description && <p className="operations-description">{scenario.description}</p>}
    {!catalogLoading && !scenarios.length && <button onClick={() => setCatalogVersion(value => value + 1)}>Tải lại kịch bản</button>}
    {error && <p className="error" role="alert">{error}</p>}
    {busy && <p role="status">Agent đang kiểm tra các ràng buộc và lưu kết quả…</p>}
    {plan && <PlanReport plan={plan} scenarioLabel={scenarios.find(item => item.id === plan.scenario_id)?.label}/>}
    <details className="operations-history"><summary>Lịch sử gần đây của chuyến này ({history.length}/10)</summary>
      <button className="operations-history-refresh" disabled={busy || historyLoading || !tripId} onClick={() => setHistoryVersion(value => value + 1)}>Làm mới lịch sử</button>
      {historyError && <p className="error" role="alert">{historyError}</p>}
      {historyLoading && <p role="status">Đang tải lịch sử…</p>}
      {!historyLoading && !history.length && !historyError && <p>Chưa có kết quả đã lưu cho chuyến đang chọn.</p>}
      <ul>{history.map(item => <li key={item.id}><button disabled={busy} onClick={() => openHistory(item.id)} aria-pressed={plan?.id === item.id}>
        {time(item.created_at)} · {scenarios.find(row => row.id === item.scenario_id)?.label || item.scenario_id} · {planStatusLabel(item.status)}
      </button></li>)}</ul>
    </details>
  </section>;
}

export default function OperationsPanel({ user, trips = [], onSessionExpired }) {
  if (user?.role !== 'operator') return null;
  return <OperationsWorkspace key={user.id || user.username} trips={trips} onSessionExpired={onSessionExpired}/>;
}
