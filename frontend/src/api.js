export async function api(path, body, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  let timedOut = false;
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(() => { timedOut = true; abort(); }, 15000);
  try {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    let data;
    try { data = await response.json(); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      // A proxy error page or incomplete JSON must not become a successful {}.
      throw Object.assign(new Error(`Máy chủ trả dữ liệu không hợp lệ (HTTP ${response.status}). Vui lòng thử lại.`), { status: response.status });
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
      throw Object.assign(new Error(detail || `HTTP ${response.status}`), { status: response.status });
    }
    return data;
  } catch (error) {
    if (timedOut) throw new Error('Máy chủ chưa phản hồi sau 15 giây. Dữ liệu đang hiển thị có thể đã cũ.');
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}

export async function apiList(path, signal) {
  const data = await api(path, undefined, signal);
  if (!Array.isArray(data)) throw new Error('Máy chủ trả danh sách không hợp lệ. Dữ liệu đang hiển thị có thể đã cũ.');
  return data;
}
