import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Collapse, Form, Input, Select, Space, Tag, Typography } from "antd";
import { Download, RefreshCw } from "lucide-react";
import { request } from "./api/client";

type Source = { source_id: string; project_id: number; requested_url: string; status: string; status_label: string;
  title?: string; text?: string; acquired_at?: string; failure_detail: string; snapshot_hash: string };

export function SupplementalSources({ projectId, selection, onChange, disabled = false }: {
  projectId: number; selection?: string[]; onChange?: (ids: string[]) => void; disabled?: boolean;
}) {
  const [rows, setRows] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [form] = Form.useForm();
  const path = `/api/v2/projects/${projectId}/supplemental-sources`;
  useEffect(() => {
    const c = new AbortController();
    let timer: number | undefined;
    setRows([]); setError(""); setLoading(true);
    async function read() {
      try {
        const result = await request<Source[]>(path, { signal: c.signal });
        if (c.signal.aborted) return;
        setRows(result.filter(r => r.project_id === projectId)); setError("");
        if (result.some(r => ["QUEUED", "RUNNING"].includes(r.status))) timer = window.setTimeout(() => void read(), 3000);
      } catch (e) { if (!c.signal.aborted) setError((e as Error).message); }
      finally { if (!c.signal.aborted) setLoading(false); }
    }
    void read();
    return () => { c.abort(); window.clearTimeout(timer); };
  }, [projectId, path, refresh]);
  async function submit(values: { url: string; fetch_authorized: boolean }) {
    setBusy(true); setError("");
    try {
      await request(path, { method: "POST", body: JSON.stringify({ ...values, idempotency_key: `public-source:${crypto.randomUUID()}` }) });
      form.resetFields(); setRefresh(n => n + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const available = rows.filter(r => ["READY", "PARTIAL"].includes(r.status));
  return <section aria-label={onChange ? "本次补充公开资料" : "补充公开资料"}>
    {error && <Alert type="error" message="补充资料读取或提交失败" description={error} />}
    {onChange ? <Space.Compact style={{ width: "100%" }}>
      <Select mode="multiple" aria-label="本次补充公开资料版本" placeholder="不使用额外公开资料" value={selection}
        onChange={onChange} maxCount={5} loading={loading} disabled={disabled || loading || !!error}
        style={{ flex: 1, minWidth: 0 }} notFoundContent="暂无已获取资料"
        options={available.map(r => ({ value: r.source_id, label: `${r.title || r.requested_url} · ${r.acquired_at || ""} · ${r.status_label}` }))} />
      <Button aria-label="刷新补充公开资料" icon={<RefreshCw size={16} />} disabled={loading || disabled} onClick={() => setRefresh(n => n + 1)} />
    </Space.Compact> : <>
      <Typography.Title level={4}>补充公开资料</Typography.Title>
      <Alert type="info" message="额外资料不计入原答案引用；获取成功不等于品牌事实已核实" />
      <Form form={form} layout="vertical" onFinish={submit} style={{ marginTop: 16 }}>
        <Form.Item label="公开页面 URL" name="url" rules={[{ required: true, type: "url" }]}><Input maxLength={1200} /></Form.Item>
        <Form.Item name="fetch_authorized" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error("请明确授权获取本页")) }]}>
          <Checkbox>允许获取此公开页面，最多两次尝试，不使用账号登录</Checkbox>
        </Form.Item>
        <Space wrap><Button type="primary" htmlType="submit" loading={busy} icon={<Download size={16} />}>获取公开资料</Button>
          <Button aria-label="刷新补充公开资料" loading={loading} icon={<RefreshCw size={16} />} onClick={() => setRefresh(n => n + 1)} /></Space>
      </Form>
      <Collapse style={{ marginTop: 16 }} items={rows.map(r => ({ key: r.source_id,
        label: <Space wrap><span>{r.title || r.requested_url}</span><Tag>{r.status_label}</Tag></Space>,
        children: <><Typography.Paragraph style={{ overflowWrap: "anywhere" }}>{r.requested_url}</Typography.Paragraph>
          {r.acquired_at && <Typography.Paragraph>资料取得时间：{r.acquired_at}</Typography.Paragraph>}
          {r.failure_detail && <Alert type="warning" message={r.failure_detail} />}
          {r.text && <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{r.text}</Typography.Paragraph>}
        </> }))} />
    </>}
  </section>;
}
