import { useState } from "react";
import { Alert, Button, Input, Modal, Space, Tag, Tooltip } from "antd";
import { ListPlus, Plus, Trash2 } from "lucide-react";
import { request } from "./api/client";

type Result = { index: number; status: "CREATED" | "EXISTING" | "REJECTED"; prompt_id: number | null; detail: string };
type Row = { key: string; text: string; result?: Result };
const blank = (): Row => ({ key: crypto.randomUUID(), text: "" });

export function ReleasePromptBatch({ projectId, onSaved }: { projectId: number; onSaved: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>([blank()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = rows.filter(row => !row.result || row.result.status === "REJECTED");
  async function save() {
    setBusy(true); setError("");
    try {
      const response = await request<{ items: Result[] }>(`/api/projects/${projectId}/prompts/batch`, {
        method: "POST", body: JSON.stringify({ items: pending.map(row => ({ prompt_text: row.text, intent_type: "unknown" })) }),
      });
      const results = new Map(response.items.map(result => [pending[result.index].key, result]));
      setRows(current => current.map(row => results.has(row.key) ? { ...row, result: results.get(row.key) } : row));
      await onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <Button icon={<ListPlus size={16} />} onClick={() => setOpen(true)}>批量添加问题</Button>
    <Modal rootClassName="release-prompt-batch" title="批量添加问题" open={open} onCancel={() => !busy && setOpen(false)} closable={!busy} maskClosable={!busy}
      footer={<Space><Button disabled={busy} onClick={() => setOpen(false)}>关闭批量添加</Button>
        <Button type="primary" loading={busy} disabled={!pending.length} onClick={save}>提交待处理问题（{pending.length}）</Button></Space>}>
      {error && <Alert type="error" message={error} />}
      {rows.map((row, index) => {
        const accepted = row.result && row.result.status !== "REJECTED";
        return <div key={row.key} style={{ marginBottom: 16 }}>
          <Space style={{ marginBottom: 4 }}><label htmlFor={`batch-${row.key}`}>问题 {index + 1}</label>
            <Tooltip title="移除此输入"><Button size="small" disabled={busy || !!accepted || rows.length === 1} aria-label={`移除问题输入${index + 1}`} icon={<Trash2 size={14} />}
              onClick={() => setRows(current => current.filter(item => item.key !== row.key))} /></Tooltip></Space>
          <Input.TextArea id={`batch-${row.key}`} value={row.text} rows={3} maxLength={10000} disabled={busy || !!accepted}
            onChange={e => setRows(current => current.map(item => item.key === row.key ? { ...item, text: e.target.value, result: undefined } : item))} />
          {row.result && <div role="status" style={{ marginTop: 4 }}><Tag color={row.result.status === "REJECTED" ? "error" : "success"}>
            {row.result.status === "CREATED" ? "已创建" : row.result.status === "EXISTING" ? "已存在" : "未创建"}</Tag>
            {row.result.detail}{row.result.prompt_id ? ` · 问题 #${row.result.prompt_id}` : ""}</div>}
        </div>;
      })}
      <Space wrap><Button disabled={busy || rows.length >= 20} icon={<Plus size={16} />} onClick={() => setRows(current => [...current, blank()])}>增加问题（{rows.length}/20）</Button>
        {!pending.length && <Button disabled={busy} icon={<ListPlus size={16} />} onClick={() => setRows([blank()])}>添加下一批</Button>}</Space>
    </Modal>
  </>;
}
