import { useState } from "react";
import { Alert, Button, Form, Input, Select, Space, Table, Typography } from "antd";
import { Pencil, Plus, Power } from "lucide-react";
import { request } from "./api/client";
import type { Prompt } from "./types";

const intents = [{ value: "category_awareness", label: "概念与知识" }, { value: "supplier_recommendation", label: "方案与工具选择" }, { value: "usage_instruction", label: "使用与操作" }];

export function ReleasePromptPanel({ projectId, prompts, onSaved }: { projectId: number; prompts: Prompt[]; onSaved: () => Promise<void> }) {
  const [form] = Form.useForm();
  const [editing, setEditing] = useState<number>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(value: any) {
    setBusy(true); setError("");
    try {
      const text = value.prompt_text.trim();
      await request(`/api/projects/${projectId}/prompts${editing ? `/${editing}` : ""}`, {
        method: editing ? "PATCH" : "POST", body: JSON.stringify({ ...value, prompt_text: text, title: text.slice(0, 60) }),
      });
      form.resetFields(); setEditing(undefined); await onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function toggle(row: Prompt) {
    setBusy(true); setError("");
    try { await request(`/api/projects/${projectId}/prompts/${row.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !row.enabled }) }); await onSaved(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section>
    {error && <Alert type="error" message={error} />}
    <Typography.Title level={4}>{editing ? "编辑问题" : "新增问题"}</Typography.Title>
    <Form form={form} layout="vertical" onFinish={save} initialValues={{ intent_type: "category_awareness", prompt_group: "" }}>
      <Form.Item label="问题原文" name="prompt_text" rules={[{ required: true, whitespace: true, message: "请输入完整问题" }]}><Input.TextArea rows={4} maxLength={10000} /></Form.Item>
      <Form.Item label="意图" name="intent_type" rules={[{ required: true }]}><Select options={intents} /></Form.Item>
      <Form.Item label="问题组（可选）" name="prompt_group"><Input maxLength={160} /></Form.Item>
      <Space><Button htmlType="submit" type="primary" loading={busy} icon={editing ? <Pencil size={16} /> : <Plus size={16} />}>{editing ? "保存问题" : "创建问题"}</Button>
        {editing && <Button onClick={() => { setEditing(undefined); form.resetFields(); }}>取消编辑</Button>}</Space>
    </Form>
    <Table style={{ marginTop: 24 }} rowKey="id" dataSource={prompts} scroll={{ x: 640 }} columns={[
      { title: "问题", dataIndex: "prompt_text", render: text => <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{text}</span> },
      { title: "意图", render: (_, r) => intents.find(x => x.value === r.intent_type)?.label || "其他已配置意图" },
      { title: "状态", render: (_, r) => r.enabled ? "可用" : "已停用" },
      { title: "操作", render: (_, r) => <Space><Button aria-label={`编辑问题${r.id}`} icon={<Pencil size={14} />} onClick={() => { setEditing(r.id); form.setFieldsValue(r); }} />
        <Button loading={busy} icon={<Power size={14} />} onClick={() => toggle(r)}>{r.enabled ? "停用" : "启用"}</Button></Space> },
    ]} />
  </section>;
}
