/**
 * Terminal markdown renderer with line-numbered code blocks
 * and SNES hex address highlighting.
 */

import React, { useMemo } from "react";
import { Text } from "ink";
import { Marked } from "marked";
import { markedTerminal } from "marked-terminal";

const marked = new Marked(
  markedTerminal({
    showSectionPrefix: false,
    tab: 2,
    // Provide a safe highlight fallback so unknown languages (e.g. "asm")
    // don't throw "could not find language" from cli-highlight.
    highlight: (code: string, _lang?: string) => code,
  }),
);

// ANSI codes for address highlighting (bold gold)
const ADDR_ON = "\x1b[1;33m";
const ADDR_OFF = "\x1b[0m";

// Match SNES-style hex addresses: $XX, $XXXX, $XXXXXX
// but only when NOT inside an ANSI escape sequence
const HEX_ADDR_RE = /(?<!\x1b\[[0-9;]*)\$[0-9A-Fa-f]{2,6}\b/g;

/**
 * Highlight $XXXX hex addresses in gold — the bread and butter of
 * SNES ROM hacking. Only applies outside of existing ANSI sequences.
 */
export function highlightHexAddresses(text: string): string {
  return text.replace(HEX_ADDR_RE, (match) => `${ADDR_ON}${match}${ADDR_OFF}`);
}

function isIndentedLine(line: string): boolean {
  return line.startsWith("    ") || line.startsWith("\t");
}

/**
 * Post-process rendered markdown to add line numbers to indented code runs.
 * Requires at least two non-empty indented lines (skipping blank lines) so a
 * single wrapped or quoted line is not mistaken for a code block.
 */
function addLineNumbers(rendered: string): string {
  const lines = rendered.split("\n");
  const n = lines.length;
  const lineNumWithinBlock = new Array<number>(n).fill(0);

  let i = 0;
  while (i < n) {
    while (i < n && (!isIndentedLine(lines[i]!) || lines[i]!.trim() === "")) {
      i++;
    }
    if (i >= n) break;

    let j = i + 1;
    let sawSecondNonEmptyIndented = false;
    while (j < n) {
      const L = lines[j]!;
      if (L.trim() === "") {
        j++;
        continue;
      }
      if (isIndentedLine(L) && L.trim() !== "") {
        sawSecondNonEmptyIndented = true;
        break;
      }
      break;
    }
    if (!sawSecondNonEmptyIndented) {
      i++;
      continue;
    }

    const blockStart = i;
    let k = i;
    while (k < n) {
      const L = lines[k]!;
      if (L.trim() === "") {
        k++;
        continue;
      }
      if (!isIndentedLine(L)) break;
      k++;
    }

    let ln = 0;
    for (let t = blockStart; t < k; t++) {
      const L = lines[t]!;
      if (isIndentedLine(L) && L.trim() !== "") {
        ln++;
        lineNumWithinBlock[t] = ln;
      }
    }
    i = k;
  }

  const result: string[] = [];
  for (let t = 0; t < n; t++) {
    const line = lines[t]!;
    const num = lineNumWithinBlock[t];
    if (num > 0) {
      const numStr = String(num).padStart(3, " ");
      result.push(`\x1b[2m${numStr}\x1b[0m ${line}`);
    } else {
      result.push(line);
    }
  }
  return result.join("\n");
}

interface MarkdownProps {
  children: string;
}

export function Markdown({ children }: MarkdownProps): React.ReactElement {
  const rendered = useMemo(() => {
    try {
      const result = marked.parse(children);
      if (typeof result === "string") {
        let output = addLineNumbers(result.replace(/\n$/, ""));
        output = highlightHexAddresses(output);
        return output;
      }
      return children;
    } catch {
      return children;
    }
  }, [children]);

  return <Text wrap="wrap">{rendered}</Text>;
}
