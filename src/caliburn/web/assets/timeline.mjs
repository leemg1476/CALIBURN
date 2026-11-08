import { SSEDecoder, acceptEvent, controlPermissions } from "./stream.mjs";

const $ = (id) => document.getElementById(id);
const terminal = new Set(["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"]);
const labels = { QUEUED: "대기 중", RUNNING: "실행 중", PAUSED: "일시정지", WAITING_APPROVAL: "독립 검토 대기", COMPLETED: "완료", FAILED: "실패", CANCELLED: "취소됨", TIMED_OUT: "시간 초과", LEASE_EXPIRED: "워커 lease 만료", PENDING: "검토 대기", APPROVED_FOR_SANDBOX_TEST: "격리 테스트 검토 승인", REJECTED: "거절됨", REVOKED: "철회됨", EXPIRED: "만료됨", INVALIDATED: "유효하지 않은 검토" };
let current = null;
function node(tag, className = "", text = "") { const item = document.createElement(tag); item.className = className; item.textContent = text; return item; }
function detail(title, value) { const item = node("details"); item.append(node("summary", "", title), node("pre", "", JSON.stringify(value, null, 2))); return item; }
function time(value) { return new Date(value * 1000).toLocaleString("ko-KR", { hour12: false }); }
function notice(message = "") { $("notice").textContent = message; $("notice").hidden = !message; }
function active(session) { return current === session && !session.controller.signal.aborted; }
function controls(session) { const allowed = controlPermissions(session?.task?.state); for (const action of ["pause", "resume", "cancel"]) $(action).disabled = !session || session.busy || !allowed[action]; }
function disconnect() {
  if (current) { current.token = ""; current.controller.abort(); clearTimeout(current.refreshTimer); }
  current = null; $("token").value = ""; $("disconnect").disabled = true; $("connection-state").textContent = "연결 해제"; controls(null);
}
class HttpFailure extends Error { constructor(status) { super("request_failed"); this.status = status; } }
async function request(session, suffix = "", options = {}) {
  if (!active(session) || !session.token) throw new DOMException("Disconnected", "AbortError");
  const response = await fetch(`/api/v1/tasks/${session.id}${suffix}`, { ...options, mode: "same-origin", credentials: "omit", cache: "no-store", redirect: "error", signal: session.controller.signal,
    headers: { ...options.headers, Authorization: `Bearer ${session.token}` } });
  if (!response.ok) throw new HttpFailure(response.status);
  return response;
}
function readableFailure(error) {
  if (error.status === 401 || error.status === 403) return "인증할 수 없습니다. 서비스 토큰을 확인하고 다시 연결하세요.";
  if (error.status === 404) return "이 계정에서 조회할 수 있는 작업이 없습니다. Task ID를 확인하세요.";
  if (error.status === 409) return "현재 작업 상태에서 요청을 처리할 수 없습니다. 최신 상태를 확인하세요.";
  return "서버 연결을 확인하세요. 마지막으로 수신한 이벤트는 유지됩니다.";
}
function handleFailure(session, error) {
  if (!active(session)) return;
  notice(readableFailure(error));
  if ([401, 403, 404].includes(error.status)) disconnect();
}
function renderTask(session) {
  if (!active(session)) return;
  const task = session.task, limits = session.limits || {};
  $("workspace").hidden = false; $("welcome").hidden = true;
  $("prompt").textContent = task.prompt.length > 240 ? task.prompt.slice(0, 240) + "…" : task.prompt;
  $("task-ref").textContent = task.id;
  $("task-state").textContent = labels[task.state] || task.state;
  $("task-state").className = "badge" + (task.state === "COMPLETED" ? " good" : ["FAILED", "TIMED_OUT", "CANCELLED"].includes(task.state) ? " bad" : "");
  $("model-count").textContent = `${task.model_calls} / ${limits.max_steps ?? "—"}`;
  $("tool-count").textContent = `${task.tool_calls} / ${limits.max_tool_calls ?? "—"}`;
  $("token-count").textContent = `${task.reserved_tokens.toLocaleString()} / ${limits.max_tokens?.toLocaleString() ?? "—"}`;
  $("cost-count").textContent = `${task.reserved_cost.toFixed(4)} / ${limits.max_cost ?? "—"}`;
  $("deadline").textContent = session.deadline ? `작업 기한 ${time(session.deadline)}` : "워커가 시작되면 작업 기한이 표시됩니다.";
  $("result-state").textContent = task.error || (task.result !== null ? "커밋된 결과" : labels[task.state] || task.state);
  const result = task.result ?? (task.error ? `작업 종료: ${task.error}` : "아직 결과가 없습니다.");
  $("result").textContent = result.slice(0, 65536) + (result.length > 65536 ? "\n… 표시 한도 초과" : "");
  controls(session);
}
function renderHistory(session) {
  const steps = [...session.steps.values()].sort((a, b) => a.ordinal - b.ordinal);
  $("step-count").textContent = `${steps.length} STEPS`; $("no-steps").hidden = !!steps.length;
  $("steps").replaceChildren(...steps.map((step) => {
    const item = node("li"), body = node("div");
    body.append(node("div", "step-title", step.kind === "MODEL" ? "모델 호출" : `도구 · ${step.tool_name || "호출"}`), node("div", "step-meta", `시도 ${step.attempts} · 실행 ${step.run_id.slice(0, 8)}`), detail("단계와 입출력 해시", step));
    item.append(node("span", "ordinal", String(step.ordinal).padStart(2, "0")), body, node("span", "step-state", step.status === "COMPLETED" ? "완료" : "미커밋")); return item;
  }));
  const runs = [...session.runs.values()].sort((a, b) => a.started_at - b.started_at || a.id.localeCompare(b.id));
  $("no-runs").hidden = !!runs.length;
  $("runs").replaceChildren(...runs.map((run, index) => { const item = node("li"); item.append(node("strong", "", `${String(index + 1).padStart(2, "0")} / ${labels[run.outcome] || run.outcome || "실행 중"}`), node("p", "mono muted", run.id.slice(0, 8)), node("p", "mono muted", time(run.started_at)), detail("실행 정보", run)); return item; }));
  $("more-history").hidden = session.nextStep === null && session.nextRun === null;
}
function renderReviews(session) {
  $("no-reviews").hidden = !!session.reviews.length;
  $("reviews").replaceChildren(...session.reviews.map((review) => { const item = node("div", "review"); item.append(node("strong", "", review.status === "PENDING" && terminal.has(session.task.state) ? "미결정 · 작업 종료" : labels[review.status] || review.status), node("p", "mono muted", review.id), node("p", "muted", review.source_executed === true ? "실행 증거 커밋됨" : review.source_executed === null ? "실행 여부 미확정" : "실행 증거 없음"), detail("정확한 검토 범위와 해시", review)); return item; }));
}
function renderEvents(session) {
  $("event-count").textContent = `${session.events.length} SHOWN · #${session.pendingCursor}`;
  $("events").replaceChildren(...session.events.map((event) => { const item = node("li"), body = node("div"); body.append(node("div", "event-name", event.type), detail("이벤트 근거", { run_id: event.run_id, actor: event.actor, ...{ payload: event.payload } })); item.append(node("span", "mono muted", `#${event.sequence}`), body, node("time", "", new Date(event.timestamp * 1000).toLocaleTimeString("ko-KR", { hour12: false }))); return item; }));
}
async function historyPage(session, afterStep = 0, runOffset = 0, maxPages = 8) {
  for (let page = 0; page < maxPages; page++) {
    const data = await (await request(session, `/history?after_step=${afterStep}&run_offset=${runOffset}&limit=100`)).json();
    if (!active(session)) return;
    session.limits = data.limits; session.deadline = data.deadline;
    for (const step of data.steps) session.steps.set(step.id, step);
    for (const run of data.runs) session.runs.set(run.id, run);
    session.nextStep = data.next_step; session.nextRun = data.next_run_offset;
    if (data.next_step === null && data.next_run_offset === null) break;
    afterStep = data.next_step ?? Math.max(0, ...[...session.steps.values()].map((step) => step.ordinal));
    runOffset = data.next_run_offset ?? session.runs.size;
  }
  renderHistory(session);
}
async function refresh(session) {
  if (session.refreshing) { session.dirty = true; return; }
  session.refreshing = true;
  try {
    const [task, reviews] = await Promise.all([request(session).then((r) => r.json()), request(session, "/reviews").then((r) => r.json())]);
    if (!active(session)) return;
    session.task = task; session.reviews = reviews;
    await historyPage(session);
    if (!active(session)) return;
    renderTask(session); renderReviews(session);
  } finally { session.refreshing = false; if (session.dirty && active(session)) { session.dirty = false; scheduleRefresh(session); } }
}
function scheduleRefresh(session) {
  if (session.refreshTimer) return;
  session.refreshTimer = setTimeout(async () => { session.refreshTimer = null; try { await refresh(session); } catch (error) { handleFailure(session, error); } }, 180);
}
async function delay(session, ms) {
  await new Promise((resolve) => { const finish = () => { clearTimeout(timer); session.controller.signal.removeEventListener("abort", finish); resolve(); }; const timer = setTimeout(finish, ms); session.controller.signal.addEventListener("abort", finish, { once: true }); });
}
async function follow(session) {
  let failures = 0;
  while (active(session)) {
    try {
      const response = await request(session, "/events", { headers: { "Last-Event-ID": String(session.cursor) } });
      $("connection-state").textContent = `실시간 연결 · 마지막 #${session.cursor}`;
      const reader = response.body.getReader(), text = new TextDecoder(), decoder = new SSEDecoder();
      try {
        while (active(session)) {
          const { value, done } = await reader.read();
          if (done) break;
          const batch = [], frames = decoder.feed(text.decode(value, { stream: true }));
          let next = session.cursor;
          for (const frame of frames) { const event = acceptEvent(frame, session.id, next); if (event) { batch.push(event); next = event.sequence; } }
          if (batch.length && active(session)) { session.events = [...session.events, ...batch].slice(-250); session.pendingCursor = next; renderEvents(session); session.cursor = next; failures = 0; $("connection-state").textContent = `실시간 연결 · 마지막 #${next}`; scheduleRefresh(session); }
        }
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      await refresh(session);
      if (active(session) && terminal.has(session.task.state) && session.cursor >= session.task.sequence) { $("connection-state").textContent = `이벤트 수신 완료 · #${session.cursor}`; return; }
    } catch (error) {
      if (!active(session)) return;
      if ([401, 403, 404].includes(error.status)) { notice(readableFailure(error)); disconnect(); return; }
      if (error.status === 409) { notice("이벤트 커서가 서버 기록보다 앞섭니다. 작업을 다시 연결해 기록을 확인하세요."); disconnect(); return; }
    }
    if (active(session)) { $("connection-state").textContent = `연결 복구 중 · 마지막 #${session.cursor}`; await delay(session, Math.min(8000, 1000 * 2 ** failures++)); }
  }
}
$("connect-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const id = $("task-id").value.trim().toLowerCase(), token = $("token").value;
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id)) { notice("Task ID는 UUID 형식이어야 합니다."); return; }
  disconnect(); notice();
  const session = { id, token, controller: new AbortController(), cursor: 0, pendingCursor: 0, events: [], steps: new Map(), runs: new Map(), reviews: [], nextStep: null, nextRun: null, refreshing: false, busy: false };
  current = session; $("disconnect").disabled = false; $("connection-state").textContent = "작업 연결 중";
  $("steps").replaceChildren(); $("events").replaceChildren(); $("runs").replaceChildren(); $("reviews").replaceChildren(); $("workspace").hidden = true; $("welcome").hidden = false;
  history.replaceState(null, "", `/tasks/ui#task=${id}`);
  try { await refresh(session); if (active(session)) await follow(session); } catch (error) { if (active(session)) { notice(readableFailure(error)); disconnect(); } }
});
$("disconnect").addEventListener("click", disconnect);
for (const action of ["pause", "resume", "cancel"]) $(action).addEventListener("click", async () => {
  const session = current; if (!session || session.busy) return; session.busy = true; controls(session); notice();
  try { await request(session, `/${action}`, { method: "POST" }); await refresh(session); } catch (error) { handleFailure(session, error); } finally { session.busy = false; if (active(session)) controls(session); }
});
$("more-history").addEventListener("click", async () => { const session = current; if (!session) return; try { await historyPage(session, session.nextStep ?? Math.max(0, ...[...session.steps.values()].map((s) => s.ordinal)), session.nextRun ?? session.runs.size); } catch (error) { handleFailure(session, error); } });
window.addEventListener("pagehide", disconnect);
const match = /^#task=([a-f0-9-]{36})$/.exec(location.hash); if (match) $("task-id").value = match[1];
