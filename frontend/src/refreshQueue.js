// Collapse a burst of WebSocket notifications into one refresh. A notification
// received during a request is retained, so the newest state is fetched next.
export function createRefreshQueue(load, {
  minimumInterval = 1000,
  now = () => Date.now(),
  schedule = (fn, delay) => setTimeout(fn, delay),
  cancel = timer => clearTimeout(timer),
  onError = () => {}
} = {}) {
  let stopped = false, running = false, pending = false, force = false;
  let timer = null, lastStarted = -Infinity;
  function plan() {
    if (stopped || running || !pending || timer !== null) return;
    timer = schedule(run, Math.max(0, minimumInterval - (now() - lastStarted)));
  }
  async function run() {
    timer = null;
    if (stopped || running || !pending) return;
    const forceNow = force;
    pending = false; force = false; running = true; lastStarted = now();
    try { await load(forceNow); }
    catch (error) { if (!stopped) onError(error); }
    finally { running = false; plan(); }
  }
  return {
    request(forceRefresh = false) {
      if (stopped) return;
      pending = true; force ||= forceRefresh; plan();
    },
    stop() {
      stopped = true; pending = false;
      if (timer !== null) cancel(timer);
      timer = null;
    }
  };
}
