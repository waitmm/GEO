import { Fragment, type ReactNode } from "react";
import { Table, Tag, Typography } from "antd";
import { parseBusinessMarkdown } from "./businessMarkdownParser";

function evidenceLabel(token: string) {
  const parts = token.slice(2, -2).split(":");
  if (parts[0] === "answer") return `回答 #${parts[1]} 依据`;
  if (parts[0] === "truth") return `品牌事实 #${parts[1]}`;
  if (parts[0] === "citation") return `引用依据 #${parts[1]}`;
  if (parts[0] === "source") return `来源依据 #${parts[1]}`;
  if (parts[0] === "observation") return "已验证范围观察";
  return "证据依据";
}

export function renderBusinessInline(text: string): ReactNode[] {
  const parts = String(text || "").split(/(\*\*[^*]+\*\*|`[^`]+`|\[\[(?:answer|truth|citation|source|observation):[^\]]+\]\])/g);
  return parts.filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <Typography.Text key={index} code>{part.slice(1, -1)}</Typography.Text>;
    if (part.startsWith("[[") && part.endsWith("]]")) return <Tag key={index} color="blue">{evidenceLabel(part)}</Tag>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function BusinessMarkdown({ markdown }: { markdown: string }) {
  const blocks = parseBusinessMarkdown(markdown);
  return <div className="business-markdown">
    {blocks.map((block, index) => {
      if (block.type === "heading") return <Typography.Title key={index} level={Math.min(5, Math.max(3, block.level + 2)) as 3 | 4 | 5}>{renderBusinessInline(block.text)}</Typography.Title>;
      if (block.type === "paragraph") return <Typography.Paragraph key={index} style={{ lineHeight: 1.8 }}>{renderBusinessInline(block.text)}</Typography.Paragraph>;
      if (block.type === "list") {
        const List = block.ordered ? "ol" : "ul";
        return <List key={index} style={{ lineHeight: 1.9, paddingLeft: 24 }}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{renderBusinessInline(item)}</li>)}</List>;
      }
      const data = block.rows.map((row, rowIndex) => ({
        ...Object.fromEntries(block.headers.map((_, cellIndex) => [String(cellIndex), row[cellIndex] || "—"])),
        key: String(rowIndex),
      }));
      return <Table key={index} size="small" pagination={false} scroll={{ x: true }} dataSource={data}
        columns={block.headers.map((header, cellIndex) => ({ title: header, dataIndex: String(cellIndex), render: (value: string) => renderBusinessInline(value) }))} />;
    })}
  </div>;
}
