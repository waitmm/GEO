import { useState } from "react";
import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { Pencil, Plus, Save, Trash2 } from "lucide-react";
import { request } from "./api/client";

type Block = { kind: "INSTRUCTION" | "SOURCE_STATEMENT" | "TARGET_STATEMENT"; text: string; evidence_ids: string[] };
type Section = { heading: string; blocks: Block[] };

export function ManuscriptEditor({ delivery, taskId, projectId, promptId, onQueued }: {
  delivery: any; taskId: string; projectId: number; promptId: number; onQueued: (task: any) => void;
}) {
  const [open, setOpen] = useState(false);
  const [sections, setSections] = useState<Section[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const valid = sections.length > 0 && sections.every(s => s.heading.trim() && s.heading.length <= 100 && s.blocks.length
    && s.blocks.every(b => b.text.trim() && b.text.length <= 1200));
  async function save() {
    setBusy(true); setError("");
    try {
      const task = await request(`/api/v2/single-prompt/optimization-tasks/${encodeURIComponent(taskId)}/draft-revisions`, {
        method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId,
          proposal_id: delivery.proposal_id, result_version: delivery.result_version, result_hash: delivery.result_hash,
          idempotency_key: `draft-edit:${crypto.randomUUID()}`, draft: { sections } }),
      });
      setOpen(false); onQueued(task);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (!delivery.editable_draft) return null;
  return <>
    <Button icon={<Pencil size={16} />} onClick={() => { setSections(structuredClone(delivery.editable_draft.sections)); setError(""); setOpen(true); }}>编辑正文并复检</Button>
    <Modal title="编辑正文" open={open} width={760} closable={!busy} maskClosable={!busy} onCancel={() => !busy && setOpen(false)}
      footer={<Space><Button disabled={busy} onClick={() => setOpen(false)}>取消编辑</Button>
        <Button type="primary" loading={busy} disabled={!valid} icon={<Save size={16} />} onClick={save}>保存修改并排队复检</Button></Space>}>
      <Alert type="info" message="旧稿保留；修改稿需重新通过文本检查。缓存不足时需要授权最多一次 QA 调用，不重跑回答或引用分析。" />
      {error && <Alert type="error" message={error} />}
      <Typography.Title level={5}>{delivery.output.publication_draft.title}</Typography.Title>
      {sections.map((section, s) => <section key={s} style={{ marginBottom: 20 }}>
        <Space style={{ width: "100%", marginBottom: 8 }}><label htmlFor={`edit-heading-${s}`}>章节 {s + 1}</label>
          <Button aria-label={`删除章节${s + 1}`} disabled={busy || sections.length === 1} icon={<Trash2 size={14} />}
            onClick={() => setSections(items => items.filter((_, i) => i !== s))} /></Space>
        <Input id={`edit-heading-${s}`} value={section.heading} disabled={busy} maxLength={100}
          onChange={e => setSections(items => items.map((item, i) => i === s ? { ...item, heading: e.target.value } : item))} />
        {section.blocks.map((block, b) => <div key={b} style={{ marginTop: 12 }}>
          <Space><label htmlFor={`edit-block-${s}-${b}`}>正文 {s + 1}.{b + 1}</label>
            <Typography.Text type="secondary">{block.kind === "INSTRUCTION" ? "行动建议" : block.kind === "SOURCE_STATEMENT" ? "来源陈述" : "目标品牌事实"}</Typography.Text>
            <Button aria-label={`删除正文${s + 1}.${b + 1}`} disabled={busy || section.blocks.length === 1} icon={<Trash2 size={14} />}
              onClick={() => setSections(items => items.map((item, i) => i === s ? { ...item, blocks: item.blocks.filter((_, j) => j !== b) } : item))} /></Space>
          <Input.TextArea id={`edit-block-${s}-${b}`} value={block.text} disabled={busy} rows={5} maxLength={1200} showCount
            onChange={e => setSections(items => items.map((item, i) => i === s ? { ...item, blocks: item.blocks.map((entry, j) => j === b ? { ...entry, text: e.target.value } : entry) } : item))} />
        </div>)}
        <Button style={{ marginTop: 20 }} disabled={busy || section.blocks.length >= 6} icon={<Plus size={14} />}
          onClick={() => setSections(items => items.map((item, i) => i === s ? { ...item, blocks: [...item.blocks, { kind: "INSTRUCTION", text: "", evidence_ids: [] }] } : item))}>增加建议段落</Button>
      </section>)}
      <Button disabled={busy || sections.length >= 8} icon={<Plus size={14} />} onClick={() => setSections(items => [...items, {
        heading: "", blocks: [{ kind: "INSTRUCTION", text: "", evidence_ids: [] }],
      }])}>增加章节</Button>
    </Modal>
  </>;
}
