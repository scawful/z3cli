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
function highlightAddresses(text: string): string {
  return text.replace(HEX_ADDR_RE, (match) => `${ADDR_ON}${match}${ADDR_OFF}`);
}

/**
 * Post-process rendered markdown to add line numbers to code blocks.
 * Detects ANSI-styled code block regions and prepends line numbers.
 */
function addLineNumbers(rendered: string): string {
  // marked-terminal wraps code blocks — look for multi-line indented sections
  // that are preceded by a blank line (typical code block output)
  const lines = rendered.split("\n");
  const result: string[] = [];
  let inCodeBlock = false;
  let codeLineNum = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    // Heuristic: code blocks from marked-terminal start with 4+ spaces or contain ANSI codes
    // after a language identifier line. We look for consecutive indented lines.
    const isIndented = line.startsWith("    ") || line.startsWith("\t");
    const nextEmpty = i < lines.length - 1 && lines[i + 1]!.trim() === "";

    if (isIndented && !inCodeBlock) {
      inCodeBlock = true;
      codeLineNum = 1;
    }

    if (inCodeBlock && !isIndented && line.trim() !== "") {
      inCodeBlock = false;
    }

    if (inCodeBlock && (isIndented || line.trim() === "")) {
      if (line.trim() === "" && nextEmpty) {
        // End of code block
        inCodeBlock = false;
        result.push(line);
      } else {
        const numStr = String(codeLineNum).padStart(3, " ");
        result.push(`\x1b[2m${numStr}\x1b[0m ${line}`);
        codeLineNum++;
      }
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
        output = highlightAddresses(output);
        return output;
      }
      return children;
    } catch {
      return children;
    }
  }, [children]);

  return <Text>{rendered}</Text>;
}
