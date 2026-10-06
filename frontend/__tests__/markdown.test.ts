import { parseInline, parseMarkdown, texToText, toPlainText } from "@/lib/markdown";

describe("parseMarkdown", () => {
  it("parses headings, paragraphs, and lists", () => {
    const blocks = parseMarkdown("### Steps\nFirst line\ncontinues.\n\n1. one\n2. two\n\n- a\n- b");
    expect(blocks.map((b) => b.type)).toEqual(["heading", "paragraph", "list", "list"]);
    expect(blocks[1]).toEqual({
      type: "paragraph",
      children: [{ type: "text", text: "First line continues." }],
    });
    expect(blocks[2]).toMatchObject({ ordered: true, start: 1, items: [{}, {}] });
    expect(blocks[3]).toMatchObject({ ordered: false });
  });

  it("nests indented list items", () => {
    const [list] = parseMarkdown("1. Load data\n   - resize to 28x28\n   - split 70/30\n2. Train");
    expect(list).toMatchObject({ type: "list", items: [{ sublist: { items: [{}, {}] } }, {}] });
  });

  it("keeps a list together across blank lines and numbers from its start", () => {
    const blocks = parseMarkdown("3. third\n\n4. fourth");
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ start: 3, items: [{}, {}] });
  });

  it("keeps code verbatim, including an unclosed fence while streaming", () => {
    const [done] = parseMarkdown("```matlab\nx = a * b * c;\n  y = **z**;\n```");
    expect(done).toEqual({ type: "code", lang: "matlab", text: "x = a * b * c;\n  y = **z**;" });
    const [open] = parseMarkdown("```\nnet = trainNetwork(");
    expect(open).toEqual({ type: "code", lang: "", text: "net = trainNetwork(" });
  });

  it("parses tables", () => {
    const [table] = parseMarkdown("| Program | Accuracy |\n|---|---:|\n| CNN | 98.67% [2] |");
    expect(table).toMatchObject({ type: "table", header: [[{ text: "Program" }], [{}]] });
    expect(table.type === "table" && table.rows[0][1]).toEqual([
      { type: "text", text: "98.67% " },
      { type: "citation", index: 2 },
    ]);
  });

  it("parses quotes and rules", () => {
    expect(parseMarkdown("> quoted\n\n---").map((b) => b.type)).toEqual(["quote", "rule"]);
  });
});

describe("parseInline", () => {
  it("parses emphasis, code, and citations", () => {
    expect(parseInline("**Adam** with `lr = 0.005` is *used* [3].")).toEqual([
      { type: "strong", children: [{ type: "text", text: "Adam" }] },
      { type: "text", text: " with " },
      { type: "code", text: "lr = 0.005" },
      { type: "text", text: " is " },
      { type: "em", children: [{ type: "text", text: "used" }] },
      { type: "text", text: " " },
      { type: "citation", index: 3 },
      { type: "text", text: "." },
    ]);
  });

  it("leaves identifiers, arithmetic, and half-streamed markers alone", () => {
    expect(parseInline("X_onehot and Y_onehot")).toEqual([
      { type: "text", text: "X_onehot and Y_onehot" },
    ]);
    expect(parseInline("2 * 3 * 4")).toEqual([{ type: "text", text: "2 * 3 * 4" }]);
    expect(parseInline("the **bottle")).toEqual([{ type: "text", text: "the **bottle" }]);
  });
});

describe("toPlainText", () => {
  it("drops Markdown syntax and citation markers", () => {
    expect(toPlainText("### Answer\nIt is **30 days** [1][2] for `bags` [3].")).toBe(
      "Answer\nIt is 30 days for bags.",
    );
  });
});

describe("LaTeX math", () => {
  it("renders simple math as readable text", () => {
    expect(
      parseInline("Prepares $1000$ images resized to $[28 \\ 28]$ in a $2 \\times 5$ grid."),
    ).toEqual([{ type: "text", text: "Prepares 1000 images resized to [28 28] in a 2 × 5 grid." }]);
    expect(texToText("\\frac{a}{b} \\leq \\text{max}")).toBe("a/b ≤ max");
  });

  it("leaves prices and code alone", () => {
    expect(parseInline("costs $5 and $10")).toEqual([{ type: "text", text: "costs $5 and $10" }]);
    expect(parseInline("`$x$`")).toEqual([{ type: "code", text: "$x$" }]);
  });

  it("strips math dollars when copying", () => {
    expect(toPlainText("Shape $[1000 \\times 784]$ [2].")).toBe("Shape [1000 × 784].");
  });
});
