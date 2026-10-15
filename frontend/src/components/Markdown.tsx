import type { ReactNode } from "react";

/**
 * Minimal markdown renderer for LLM-drafted briefs and exported reports:
 * headings, bold/italic/code inline, unordered lists, pipe tables, hr.
 * Deliberately dependency-free — the brief content is model output, so the
 * renderer stays small and predictable.
 */

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(
        <strong key={`${keyPrefix}-b${i}`} className="font-semibold">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`")) {
      nodes.push(
        <code key={`${keyPrefix}-c${i}`} className="rounded bg-muted px-1 font-mono text-[0.85em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      nodes.push(<em key={`${keyPrefix}-i${i}`}>{token.slice(1, -1)}</em>);
    }
    last = match.index + token.length;
    i += 1;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function isTableDivider(line: string): boolean {
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(line.trim());
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

export default function Markdown({ source }: { source: string }) {
  const lines = source.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let key = 0;

  const flushList = () => {
    if (list.length === 0) return;
    const items = list;
    list = [];
    blocks.push(
      <ul key={`ul-${key++}`} className="list-disc space-y-1 pl-5">
        {items.map((item, j) => (
          <li key={j}>{renderInline(item, `li-${key}-${j}`)}</li>
        ))}
      </ul>,
    );
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      flushList();
      const header = splitRow(trimmed);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      blocks.push(
        <div key={`tbl-${key++}`} className="overflow-x-auto">
          <table className="w-full border-collapse text-[0.85em]">
            <thead>
              <tr>
                {header.map((cell, j) => (
                  <th key={j} className="border-b px-2 py-1 text-left font-semibold">
                    {renderInline(cell, `th-${key}-${j}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border-b border-muted px-2 py-1 align-top">
                      {renderInline(cell, `td-${key}-${r}-${c}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      list.push(trimmed.slice(2));
      i += 1;
      continue;
    }

    flushList();

    if (trimmed === "") {
      // skip blank
    } else if (trimmed.startsWith("### ")) {
      blocks.push(
        <h3 key={`h3-${key++}`} className="mt-3 text-sm font-semibold">
          {renderInline(trimmed.slice(4), `h3-${key}`)}
        </h3>,
      );
    } else if (trimmed.startsWith("## ")) {
      blocks.push(
        <h2 key={`h2-${key++}`} className="mt-4 border-b pb-1 text-sm font-semibold">
          {renderInline(trimmed.slice(3), `h2-${key}`)}
        </h2>,
      );
    } else if (trimmed.startsWith("# ")) {
      blocks.push(
        <h1 key={`h1-${key++}`} className="text-base font-bold">
          {renderInline(trimmed.slice(2), `h1-${key}`)}
        </h1>,
      );
    } else if (/^-{3,}$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${key++}`} className="my-3 border-muted" />);
    } else {
      blocks.push(
        <p key={`p-${key++}`} className="leading-relaxed">
          {renderInline(trimmed, `p-${key}`)}
        </p>,
      );
    }
    i += 1;
  }
  flushList();

  return <div className="space-y-2 text-sm">{blocks}</div>;
}
