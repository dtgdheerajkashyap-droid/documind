/**
 * Minimal Server-Sent Events parser for `fetch` streams.
 *
 * `EventSource` only supports GET, but the chat endpoint is a POST, so we read
 * the response body ourselves and split it into events.
 */

export interface SSEMessage {
  event: string;
  data: string;
}

export function parseSSEBlock(block: string): SSEMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // blank or comment
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

/** Feed arbitrary text chunks; `onMessage` fires once per complete event. */
export function createSSEParser(onMessage: (message: SSEMessage) => void) {
  let buffer = "";
  return {
    feed(chunk: string) {
      buffer += chunk.replace(/\r\n?/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const message = parseSSEBlock(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (message) onMessage(message);
        boundary = buffer.indexOf("\n\n");
      }
    },
    flush() {
      const message = parseSSEBlock(buffer);
      buffer = "";
      if (message) onMessage(message);
    },
  };
}
