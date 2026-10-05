import { createSSEParser, parseSSEBlock } from "@/lib/sse";

describe("parseSSEBlock", () => {
  it("reads event name and data", () => {
    expect(parseSSEBlock('event: token\ndata: {"text":"hi"}')).toEqual({
      event: "token",
      data: '{"text":"hi"}',
    });
  });

  it("defaults the event name and ignores comments", () => {
    expect(parseSSEBlock(": keep-alive\ndata: x")).toEqual({ event: "message", data: "x" });
  });

  it("returns null when there is no data", () => {
    expect(parseSSEBlock("event: ping")).toBeNull();
  });
});

describe("createSSEParser", () => {
  it("emits events split across arbitrary chunk boundaries", () => {
    const events: { event: string; data: string }[] = [];
    const parser = createSSEParser((e) => events.push(e));

    parser.feed('event: meta\ndata: {"a"');
    parser.feed(":1}\n\nevent: tok");
    parser.feed('en\r\ndata: {"text":"x"}\r\n\r\n');

    expect(events).toEqual([
      { event: "meta", data: '{"a":1}' },
      { event: "token", data: '{"text":"x"}' },
    ]);
  });

  it("flushes a trailing event without a blank line", () => {
    const events: { event: string; data: string }[] = [];
    const parser = createSSEParser((e) => events.push(e));
    parser.feed("event: done\ndata: {}");
    expect(events).toHaveLength(0);
    parser.flush();
    expect(events).toEqual([{ event: "done", data: "{}" }]);
  });
});
