export type BusinessMarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] };

const headingPattern = /^(#{1,5})\s+(.+)$/;
const unorderedPattern = /^[-*]\s+(.+)$/;
const orderedPattern = /^\d+[.)]\s+(.+)$/;
const tableDividerPattern = /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/;

function tableCells(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(value => value.trim());
}

export function parseBusinessMarkdown(markdown: string): BusinessMarkdownBlock[] {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: BusinessMarkdownBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }
    const heading = line.match(headingPattern);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() });
      index += 1; continue;
    }
    if (index + 1 < lines.length && line.includes("|") && tableDividerPattern.test(lines[index + 1])) {
      const headers = tableCells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(tableCells(lines[index])); index += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }
    const unordered = line.match(unorderedPattern);
    const ordered = line.match(orderedPattern);
    if (unordered || ordered) {
      const isOrdered = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const match = lines[index].trim().match(isOrdered ? orderedPattern : unorderedPattern);
        if (!match) break;
        items.push(match[1].trim()); index += 1;
      }
      blocks.push({ type: "list", ordered: isOrdered, items });
      continue;
    }
    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length) {
      const next = lines[index].trim();
      if (!next || headingPattern.test(next) || unorderedPattern.test(next) || orderedPattern.test(next)
        || (index + 1 < lines.length && next.includes("|") && tableDividerPattern.test(lines[index + 1]))) break;
      paragraph.push(next); index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }
  return blocks;
}
