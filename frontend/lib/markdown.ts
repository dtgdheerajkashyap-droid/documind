/**
 * A small Markdown parser for answers: the subset a model writes (headings, paragraphs,
 * lists, code blocks, tables, quotes, bold/italic/code) and nothing that could inject
 * HTML. It never throws, and half-streamed input ("**bol", an open ``` fence) still parses.
 */

export type Inline =
  | { type: "text"; text: string }
  | { type: "strong"; children: Inline[] }
  | { type: "em"; children: Inline[] }
  | { type: "code"; text: string }
  | { type: "citation"; index: number };

export interface ListItem {
  children: Inline[];
  sublist?: ListBlock;
}

export interface ListBlock {
  type: "list";
  ordered: boolean;
  start: number;
  items: ListItem[];
}

export type Block =
  | { type: "heading"; level: number; children: Inline[] }
  | { type: "paragraph"; children: Inline[] }
  | { type: "code"; lang: string; text: string }
  | { type: "quote"; children: Inline[] }
  | { type: "table"; header: Inline[][]; rows: Inline[][][] }
  | { type: "rule" }
  | ListBlock;

const FENCE = /^\s*(```|~~~)\s*([\w+#.-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const LIST_ITEM = /^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      i++; // closing fence (or end of a still-streaming answer)
      blocks.push({ type: "code", lang: fence[2], text: dedent(body).join("\n") });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({
        type: "heading",
        level: heading[1].length,
        children: parseInline(heading[2]),
      });
      i++;
      continue;
    }

    if (RULE.test(line)) {
      blocks.push({ type: "rule" });
      i++;
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
      const header = splitRow(line);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(splitRow(lines[i++]));
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        body.push(lines[i++].replace(/^\s*>\s?/, ""));
      }
      blocks.push({ type: "quote", children: parseInline(body.join(" ")) });
      continue;
    }

    if (LIST_ITEM.test(line)) {
      const start = i;
      const first = LIST_ITEM.exec(line)!;
      // A top-level item of the other kind (bullets after steps) starts a new list.
      const sameList = (l: string) => {
        const item = LIST_ITEM.exec(l);
        return (
          !item ||
          item[1].length > first[1].length + 1 ||
          /\d/.test(item[2]) === /\d/.test(first[2])
        );
      };
      while (
        i < lines.length &&
        ((LIST_ITEM.test(lines[i]) && (i === start || sameList(lines[i]))) ||
          (lines[i].trim() && /^\s+/.test(lines[i]) && !FENCE.test(lines[i])) ||
          (!lines[i].trim() &&
            i + 1 < lines.length &&
            LIST_ITEM.test(lines[i + 1]) &&
            sameList(lines[i + 1])))
      ) {
        i++;
      }
      blocks.push(parseList(lines.slice(start, i).filter((l) => l.trim())));
      continue;
    }

    const body: string[] = [];
    while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) body.push(lines[i++]);
    if (body.length === 0) body.push(lines[i++]);
    blocks.push({ type: "paragraph", children: parseInline(body.join(" ")) });
  }
  return blocks;
}

function startsBlock(lines: string[], i: number): boolean {
  const line = lines[i];
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    LIST_ITEM.test(line) ||
    /^\s*>/.test(line) ||
    (line.includes("|") && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1]))
  );
}

/** Items at the smallest indentation; deeper lines become their sublists. */
function parseList(lines: string[]): ListBlock {
  const first = LIST_ITEM.exec(lines[0])!;
  const base = first[1].length;
  const ordered = /\d/.test(first[2]);
  const list: ListBlock = {
    type: "list",
    ordered,
    start: ordered ? parseInt(first[2], 10) : 1,
    items: [],
  };

  let text: string[] = [];
  let nested: string[] = [];
  const flush = () => {
    if (text.length === 0 && nested.length === 0) return;
    const item: ListItem = { children: parseInline(text.join(" ")) };
    if (nested.length > 0) item.sublist = parseList(nested);
    list.items.push(item);
    text = [];
    nested = [];
  };

  for (const line of lines) {
    const item = LIST_ITEM.exec(line);
    if (item && item[1].length <= base + 1) {
      flush();
      text.push(item[3]);
    } else if (item || nested.length > 0) {
      nested.push(line);
    } else {
      text.push(line.trim()); // continuation of the current item
    }
  }
  flush();
  return list;
}

function splitRow(line: string): Inline[][] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => parseInline(cell.trim()));
}

function dedent(lines: string[]): string[] {
  const indents = lines.filter((l) => l.trim()).map((l) => /^\s*/.exec(l)![0].length);
  const cut = indents.length ? Math.min(...indents) : 0;
  return lines.map((l) => l.slice(cut));
}

// Underscores only emphasise at word boundaries, so identifiers such as X_onehot stay intact.
// $...$ is LaTeX math (no space just inside the dollars, so "$5 and $10" is left alone).
const INLINE =
  /(`[^`]+`|\$(?=\S)[^$\n]+?(?<=\S)\$(?!\d)|\*\*[^*]+?\*\*|(?<!\w)__[^_]+?__(?!\w)|\*[^*\s][^*]*?\*|(?<!\w)_[^_\s][^_]*?_(?!\w)|\[\d{1,2}\])/;

const TEX_SYMBOLS: Record<string, string> = {
  times: "×",
  cdot: "·",
  div: "÷",
  pm: "±",
  leq: "≤",
  le: "≤",
  geq: "≥",
  ge: "≥",
  neq: "≠",
  approx: "≈",
  to: "→",
  rightarrow: "→",
  leftarrow: "←",
  infty: "∞",
  alpha: "α",
  beta: "β",
  gamma: "γ",
  lambda: "λ",
  mu: "μ",
  sigma: "σ",
  theta: "θ",
  eta: "η",
};

/** Simple LaTeX math as readable text: "$2 \times 5$" -> "2 × 5", "$\frac{a}{b}$" -> "a/b". */
export function texToText(tex: string): string {
  return tex
    .replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, "$1/$2")
    .replace(/\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}/g, "$1")
    .replace(/\\([a-zA-Z]+)/g, (match, name: string) => TEX_SYMBOLS[name] ?? match.slice(1))
    .replace(/\\[ ,;:!]/g, " ")
    .replace(/\^\{([^{}]*)\}/g, "^$1")
    .replace(/_\{([^{}]*)\}/g, "_$1")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const pushText = (value: string) => {
    const last = out.at(-1);
    if (last?.type === "text") last.text += value;
    else out.push({ type: "text", text: value });
  };
  for (const part of text.split(INLINE)) {
    if (!part) continue;
    if (/^`[^`]+`$/.test(part)) {
      out.push({ type: "code", text: part.slice(1, -1) });
    } else if (/^\$.+\$$/.test(part)) {
      pushText(texToText(part.slice(1, -1)));
    } else if (/^(\*\*|__).+\1$/.test(part)) {
      out.push({ type: "strong", children: parseInline(part.slice(2, -2)) });
    } else if (/^\[\d{1,2}\]$/.test(part)) {
      out.push({ type: "citation", index: Number(part.slice(1, -1)) });
    } else if (/^([*_]).+\1$/.test(part) && part.length > 2) {
      out.push({ type: "em", children: parseInline(part.slice(1, -1)) });
    } else {
      pushText(part);
    }
  }
  return out;
}

/** Answer text without Markdown syntax or citation markers, e.g. for copying. */
export function toPlainText(source: string): string {
  return source
    .replace(/\s*\[\d{1,2}\]/g, "")
    .replace(/^\s*(```|~~~).*$/gm, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\$(?=\S)([^$\n]+?)(?<=\S)\$(?!\d)/g, (_, tex: string) => texToText(tex))
    .trim();
}
