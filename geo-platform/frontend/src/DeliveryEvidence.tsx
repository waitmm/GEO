import { useState } from "react";
import { Alert, Button, Collapse, Descriptions, Empty, Modal, Select, Space, Tabs, Tag, Typography } from "antd";
import { BookOpen, Locate } from "lucide-react";
import { evidenceLink, locateAnswer, type AnswerUnit, type FrozenAnswer } from "./api/evidence";

type Evidence = {
  section_id: string; title: string; url: string; snapshot_id: string; passage_id: string;
  passage_text: string; source_span?: string; evidence_relation?: string;
  answer_unit?: AnswerUnit; answer_anchor?: string; generation_influence?: string;
};
type FrozenInput = {
  prompt_text: string; answers: FrozenAnswer[]; selected_evidence: Evidence[];
  raw_result_version: string; answer_result_version: string; contribution_result_version?: string;
  brand: { brand_name: string }; truths: { product_truth_id: number; capability_label: string; public_use_eligibility: string; source_reference: string }[];
  brand_context?: { context_version_id?: string; title?: string; passages?: { passage_id: string; text: string; source_reference: string }[] };
};
const paragraphStyle = { whiteSpace: "pre-wrap" as const, overflowWrap: "anywhere" as const };

function SourceLink({ value }: { value: string }) {
  const href = evidenceLink(value);
  return href ? <Typography.Link href={href} target="_blank" rel="noopener noreferrer" style={{ overflowWrap: "anywhere", color: "#0759a3", textDecoration: "underline" }}>{value}</Typography.Link>
    : <Typography.Text style={{ overflowWrap: "anywhere" }}>{value || "未记录出处"}</Typography.Text>;
}

export function DeliveryEvidence({ frozen, resultVersion }: { frozen: FrozenInput; resultVersion: string }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("answers");
  const [runId, setRunId] = useState(frozen.answers[0]?.run_id);
  const [unit, setUnit] = useState<AnswerUnit>();
  const answer = frozen.answers.find(row => row.run_id === runId);
  const location = unit && unit.run_id === runId ? locateAnswer(frozen.answers, unit) : null;
  const context = frozen.brand_context;
  return <>
    <Button icon={<BookOpen size={16} />} onClick={() => setOpen(true)}>查看分析依据</Button>
    <Modal title="方案依据与原始回答" open={open} onCancel={() => setOpen(false)} footer={null}
      width={900} styles={{ body: { overflowWrap: "anywhere" } }}>
      <Typography.Title level={5}>{frozen.prompt_text}</Typography.Title>
      <Typography.Paragraph type="secondary">{frozen.brand.brand_name} · {resultVersion}</Typography.Paragraph>
      <Tabs activeKey={tab} onChange={setTab} items={[
        { key: "answers", label: "回答原文", children: <>
          <Select aria-label="依据中的回答样本" value={runId} style={{ width: "100%", marginBottom: 16 }}
            onChange={value => { setRunId(value); setUnit(undefined); }}
            options={frozen.answers.map(row => ({ value: row.run_id, label: `Run #${row.run_id}` }))} />
          {answer ? <section aria-label={`Run ${answer.run_id} 完整回答`}>
            <Typography.Paragraph type="secondary">这是该次采样的完整回答，不代表其中的产品能力已经核实。</Typography.Paragraph>
            {unit && !location && <Alert type="warning" message="片段定位与本版原文不一致，保留完整原回答，不猜测位置" />}
            <Typography.Paragraph style={paragraphStyle}>{location ? <>{location.before}<mark>{location.text}</mark>{location.after}</> : answer.text}</Typography.Paragraph>
          </section> : <Empty description="本版未保存可展示的回答原文" />}
        </> },
        { key: "sources", label: "来源证据", children: <>
          <Alert type="info" showIcon message="以下仅是本方案选用的证据，不是全部引用的使用率；内容支持不能证明模型实际采用了该来源。" />
          {!frozen.selected_evidence.length && <Empty description="本方案没有采用已合格的正文支持关系；查证建议不等于已证实事实" />}
          {frozen.selected_evidence.map((item, index) => <section key={item.section_id} aria-label={`来源证据 ${index + 1}`} style={{ padding: "16px 0", borderBottom: "1px solid #e5e7eb" }}>
            <Typography.Title level={5}>{item.title || `来源 ${index + 1}`}</Typography.Title>
            <SourceLink value={item.url} />
            <Space wrap style={{ margin: "12px 0" }}>
              <Tag>{item.evidence_relation === "SUPPORTS_FULL" ? "支持当前表述" : item.evidence_relation === "SUPPORTS_PARTIAL" ? "仅部分支持" : "页面观察，未证明支持"}</Tag>
              <Tag>{item.answer_anchor === "UNPROVEN" ? "原回答引用锚点未证实" : "引用锚点见原始记录"}</Tag>
              <Tag>生成影响未确定</Tag>
            </Space>
            {item.answer_unit && <>
              <Typography.Text strong>对应回答片段 · Run #{item.answer_unit.run_id}</Typography.Text>
              <Typography.Paragraph style={paragraphStyle}>{item.answer_unit.raw_text}</Typography.Paragraph>
              <Button size="small" icon={<Locate size={14} />} onClick={() => {
                setRunId(item.answer_unit!.run_id); setUnit(item.answer_unit); setTab("answers");
              }}>定位完整回答</Button>
            </>}
            <Typography.Paragraph strong style={{ marginTop: 16 }}>来源段落原文</Typography.Paragraph>
            <Typography.Paragraph style={paragraphStyle}>{item.passage_text}</Typography.Paragraph>
            <Collapse size="small" items={[{ key: "binding", label: "来源版本", children: <Descriptions column={1} size="small">
              <Descriptions.Item label="正文快照">{item.snapshot_id}</Descriptions.Item>
              <Descriptions.Item label="段落">{item.passage_id}</Descriptions.Item>
            </Descriptions> }]} />
          </section>)}
        </> },
        { key: "brand", label: "品牌资料", children: <>
          <Typography.Title level={5}>本版采用的品牌事实</Typography.Title>
          {!frozen.truths.length && <Empty description="本版没有采用已核实品牌事实；这不表示品牌没有相应能力" />}
          {frozen.truths.map(truth => <section key={truth.product_truth_id} style={{ marginBottom: 16 }}>
            <Typography.Paragraph>{truth.capability_label}</Typography.Paragraph>
            <Tag>{truth.public_use_eligibility === "CONSUMABLE" ? "本版可用于公开草稿" : "不能据此作公开能力声明"}</Tag>
            <SourceLink value={truth.source_reference} />
          </section>)}
          <Typography.Title level={5}>补充上下文</Typography.Title>
          {!context?.passages?.length ? <Typography.Paragraph>未选择相关补充资料。</Typography.Paragraph> : <>
            <Alert type="warning" message="用户提供的内部资料，未独立核实，不自动成为公开事实" />
            <Typography.Paragraph>{context.title} · {context.context_version_id}</Typography.Paragraph>
            {context.passages.map(passage => <section key={passage.passage_id}>
              <Typography.Paragraph style={paragraphStyle}>{passage.text}</Typography.Paragraph>
              <SourceLink value={passage.source_reference} />
            </section>)}
          </>}
        </> },
      ]} />
      <Collapse size="small" items={[{ key: "versions", label: "本次分析版本", children: <Descriptions size="small" column={1}>
        <Descriptions.Item label="采样结果">{frozen.raw_result_version}</Descriptions.Item>
        <Descriptions.Item label="回答分析">{frozen.answer_result_version}</Descriptions.Item>
        <Descriptions.Item label="引用贡献">{frozen.contribution_result_version || "未消费引用贡献版本"}</Descriptions.Item>
      </Descriptions> }]} />
    </Modal>
  </>;
}
