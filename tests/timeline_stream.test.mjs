import test from "node:test";
import assert from "node:assert/strict";
import { SSEDecoder, acceptEvent, controlPermissions } from "../src/caliburn/web/assets/stream.mjs";

const task = "a-task";
function frame(sequence, fields = {}) { return { id: String(sequence), type: "STEP_STARTED", data: JSON.stringify({ task_id: task, sequence, type: "STEP_STARTED", ...fields }) }; }
test("split UTF8 SSE, CRLF, comments and multi-data framing", () => {
  const encoder = new TextEncoder(), decoder = new TextDecoder(), parser = new SSEDecoder();
  const bytes = encoder.encode(': heartbeat\r\n\r\nid: 1\r\nevent: STEP_STARTED\r\ndata: {"task_id":"a-task",\r\ndata: "sequence":1,"type":"STEP_STARTED","payload":"한글 <script>"}\r\n\r\n');
  const events = [];
  for (const byte of bytes) events.push(...parser.feed(decoder.decode(Uint8Array.of(byte), { stream: true })));
  assert.equal(events.length, 1);
  assert.equal(acceptEvent(events[0], task, 0).payload, "한글 <script>");
});
test("replay is contiguous, duplicates ignored, gaps never advance cursor", () => {
  assert.equal(acceptEvent(frame(1), task, 1), null);
  assert.equal(acceptEvent(frame(2), task, 1).sequence, 2);
  assert.throws(() => acceptEvent(frame(3), task, 1), /event_gap/);
  assert.throws(() => acceptEvent(frame(2, { task_id: "foreign" }), task, 1), /identity/);
  assert.throws(() => acceptEvent(frame(2, { sequence: 5 }), task, 1), /identity/);
});
test("bounded frames and approval gate control semantics", () => {
  assert.throws(() => new SSEDecoder().feed("a".repeat(1_048_577)), /limit/);
  assert.deepEqual(controlPermissions("WAITING_APPROVAL"), { pause: false, resume: false, cancel: true });
  assert.equal(controlPermissions("PAUSED").resume, true);
  assert.equal(controlPermissions("COMPLETED").cancel, false);
});
