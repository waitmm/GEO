import { Empty, Typography } from "antd";
import { evidenceLink } from "./api/evidence";

type Section = { section_id: string; title: string; draft_text: string; evidence_ids: string[] };

export function ManuscriptPreview({ output }: { output: any }) {
  const sources = new Map<string, string>();
  for (const item of output.delivery_input.selected_evidence || []) sources.set(item.section_id, item.url);
  for (const item of output.delivery_input.truths || []) sources.set(`truth:${item.product_truth_id}`, item.source_reference);
  for (const item of output.generation_receipt?.official_facts?.accepted || []) sources.set(item.fact_id, item.url);
  const sections: Section[] = output.publication_draft.sections;
  return <article aria-label="完整稿件正文" style={{ marginTop: 24, overflowWrap: "anywhere" }}>
    {!sections.length && <Empty description="尚未形成完整正文" />}
    {sections.map(section => <section key={section.section_id} style={{ margin: "20px 0" }}>
      <Typography.Title level={5}>{section.title}</Typography.Title>
      <Typography.Paragraph style={{ whiteSpace: "pre-wrap", lineHeight: 1.8 }}>{section.draft_text}</Typography.Paragraph>
      {[...new Set((section.evidence_ids || []).map(id => sources.get(id)).filter((url): url is string => !!url))].map(url => {
        const href = evidenceLink(url);
        return <Typography.Paragraph key={url} style={{ fontSize: 13 }}>
          来源：{href ? <Typography.Link href={href} target="_blank" rel="noopener noreferrer"
            style={{ color: "#0759a3", textDecoration: "underline" }}>{url}</Typography.Link> : url}
        </Typography.Paragraph>;
      })}
    </section>)}
  </article>;
}
