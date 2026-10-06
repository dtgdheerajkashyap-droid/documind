"use client";

import { Fragment, type ReactNode } from "react";

import { type Block, type Inline, type ListBlock, parseMarkdown } from "@/lib/markdown";

interface Props {
  content: string;
  /** Source numbers that exist; other [n] markers stay plain text. */
  citations: Set<number>;
  activeCitation?: number | null;
  onCitationClick?: (index: number) => void;
  streaming?: boolean;
}

/** Render a Markdown answer, turning [n] markers that match a citation into buttons. */
export function Markdown({
  content,
  citations,
  activeCitation,
  onCitationClick,
  streaming,
}: Props) {
  const inline = (nodes: Inline[]): ReactNode =>
    nodes.map((node, i) => {
      switch (node.type) {
        case "text":
          return <Fragment key={i}>{node.text}</Fragment>;
        case "strong":
          return <strong key={i}>{inline(node.children)}</strong>;
        case "em":
          return <em key={i}>{inline(node.children)}</em>;
        case "code":
          return <code key={i}>{node.text}</code>;
        case "citation":
          if (!citations.has(node.index)) return <Fragment key={i}>[{node.index}]</Fragment>;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onCitationClick?.(node.index)}
              aria-label={`Show source ${node.index}`}
              className={`citation-marker ${activeCitation === node.index ? "is-active" : ""}`}
            >
              {node.index}
            </button>
          );
      }
    });

  const list = (block: ListBlock, key: number | string): ReactNode => {
    const items = block.items.map((item, i) => (
      <li key={i}>
        {inline(item.children)}
        {item.sublist && list(item.sublist, "sub")}
      </li>
    ));
    return block.ordered ? (
      <ol key={key} start={block.start === 1 ? undefined : block.start}>
        {items}
      </ol>
    ) : (
      <ul key={key}>{items}</ul>
    );
  };

  const block = (b: Block, i: number): ReactNode => {
    switch (b.type) {
      case "heading": {
        // Answers sit under the chat's own title, so "#" renders as a section heading.
        const Tag = (["h3", "h3", "h4", "h5", "h5", "h5"] as const)[b.level - 1];
        return <Tag key={i}>{inline(b.children)}</Tag>;
      }
      case "paragraph":
        return <p key={i}>{inline(b.children)}</p>;
      case "code":
        return (
          <figure key={i} className="code-block">
            {b.lang && <figcaption>{b.lang}</figcaption>}
            <pre>
              <code>{b.text}</code>
            </pre>
          </figure>
        );
      case "quote":
        return <blockquote key={i}>{inline(b.children)}</blockquote>;
      case "table":
        return (
          <div key={i} className="table-wrap">
            <table>
              <thead>
                <tr>
                  {b.header.map((cell, c) => (
                    <th key={c}>{inline(cell)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c}>{inline(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case "rule":
        return <hr key={i} />;
      case "list":
        return list(b, i);
    }
  };

  return (
    <div className={`answer-prose ${streaming ? "is-streaming" : ""}`}>
      {parseMarkdown(content).map(block)}
    </div>
  );
}
