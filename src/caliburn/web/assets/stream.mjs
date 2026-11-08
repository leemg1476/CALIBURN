/** Bounded SSE framing and contiguous replay cursor. No credentials or persistence. */
export class SSEDecoder {
  constructor() { this.buffer = ""; }
  feed(text) {
    this.buffer += text;
    if (this.buffer.length > 1_048_576) throw new Error("event_frame_limit");
    const events = [];
    let boundary;
    while ((boundary = /\r?\n\r?\n/.exec(this.buffer)) !== null) {
      const frame = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      let id = "", type = "message";
      const data = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "id") id = value;
        if (field === "event") type = value;
        if (field === "data") data.push(value);
      }
      if (data.length) events.push({ id, type, data: data.join("\n") });
    }
    return events;
  }
}

export function acceptEvent(frame, taskId, after) {
  const event = JSON.parse(frame.data);
  const sequence = Number(frame.id);
  if (!/^\d+$/.test(frame.id) || !Number.isSafeInteger(sequence) || sequence < 1 || event.task_id !== taskId || event.sequence !== sequence || event.type !== frame.type) throw new Error("invalid_event_identity");
  if (sequence <= after) return null;
  if (sequence !== after + 1) throw new Error("event_gap");
  return event;
}

export function controlPermissions(state) {
  return { pause: ["QUEUED", "RUNNING"].includes(state), resume: state === "PAUSED", cancel: ["QUEUED", "RUNNING", "PAUSED", "WAITING_APPROVAL"].includes(state) };
}
