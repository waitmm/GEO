import { useEffect, useState } from "react";
import { Alert, Button, Descriptions, Form, Input, Select, Space, Tag, Typography } from "antd";
import { ClipboardPaste, ShieldCheck } from "lucide-react";
import { api, request } from "./api/client";
import type { PromptVersion } from "./types";
import { beijingDateTimeLocalValue, beijingLocalDateTimeToIso, formatBeijingDateTime } from "./time";

type ConfigurationVersion = {
  configuration_version_id: string;
  version_number: number;
  status: string;
  snapshot_hash: string;
  created_at: string;
};

type Preview = {
  promptVersion: PromptVersion;
  configurationVersion: ConfigurationVersion;
  payload: Record<string, unknown>;
  citationCount: number;
};

function localDateTimeNow() {
  return beijingDateTimeLocalValue();
}

function citationsFrom(text: string) {
  return String(text || "").split("\n").map(line => line.trim()).filter(Boolean).map((line, index) => {
    const separator = line.includes("|") ? "|" : "";
    const parts = separator ? line.split(separator) : [line];
    const url = (separator ? parts.pop() : parts[0])!.trim();
    const title = separator ? parts.join("|").trim() : `引用 ${index + 1}`;
    if (!/^https?:\/\//i.test(url)) throw new Error(`第 ${index + 1} 条引用不是完整的 http/https URL`);
    return { title, url };
  });
}

export function ManualImportPanel({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [form] = Form.useForm();
  const citationStatus = Form.useWatch("citation_observation_status", form) || "UNKNOWN";
  const [promptVersions, setPromptVersions] = useState<PromptVersion[]>([]);
  const [configVersions, setConfigVersions] = useState<ConfigurationVersion[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [result, setResult] = useState<any>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setPreview(undefined); setResult(undefined); setError("");
    Promise.all([
      api.listPromptVersions(projectId, promptId),
      request<ConfigurationVersion[]>(`/api/projects/${projectId}/configuration-versions`),
    ]).then(([prompts, configs]) => {
      if (cancelled) return;
      setPromptVersions(prompts); setConfigVersions(configs);
      form.setFieldsValue({
        observed_at: localDateTimeNow(), source_platform: "wenxin",
        citation_observation_status: "UNKNOWN",
      });
    }).catch(e => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [projectId, promptId, form]);

  function buildPreview(values: any) {
    setError(""); setResult(undefined);
    try {
      const promptVersion = promptVersions.find(item => item.prompt_version_id === values.prompt_version_id);
      const configurationVersion = configVersions.find(item => item.configuration_version_id === values.configuration_version_id);
      if (!promptVersion || !configurationVersion) throw new Error("请选择这条回答对应的问题版本和品牌资料版本");
      const citations = citationsFrom(values.citations_text || "");
      if (values.citation_observation_status === "CONFIRMED_NONE" && citations.length) throw new Error("已确认无引用时不能填写引用 URL");
      if (values.citation_observation_status === "COMPLETE" && !citations.length) throw new Error("完整引用记录至少需要一条 URL");
      if (["UNKNOWN", "PARSE_FAILED"].includes(values.citation_observation_status) && !String(values.citation_note || "").trim()) throw new Error("引用未知或解析失败时必须填写说明");
      const payload = {
        prompt_version_id: promptVersion.prompt_version_id,
        prompt_snapshot_hash: promptVersion.snapshot_hash,
        configuration_version_id: configurationVersion.configuration_version_id,
        configuration_snapshot_hash: configurationVersion.snapshot_hash,
        observed_at: beijingLocalDateTimeToIso(values.observed_at), source_platform: "wenxin",
        source_page_url: values.source_page_url || "", answer_text: values.answer_text,
        citations, citation_observation_status: values.citation_observation_status,
        citation_note: values.citation_note || "", idempotency_key: crypto.randomUUID(),
      };
      setPreview({ promptVersion, configurationVersion, payload, citationCount: citations.length });
    } catch (e) { setPreview(undefined); setError((e as Error).message); }
  }

  async function submit() {
    if (!preview) return;
    setBusy(true); setError("");
    try {
      const value = await request<any>(`/api/v2/projects/${projectId}/prompts/${promptId}/manual-imports`, {
        method: "POST", body: JSON.stringify(preview.payload),
      });
      setResult(value); setPreview(undefined);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <section aria-label="人工导入真实 AI 回答">
    <Typography.Title level={4}>人工导入回答</Typography.Title>
    <Alert type="warning" showIcon message="人工来源声明，不是平台真实性认证"
      description="系统会校验项目、观察时有效的版本、内容完整性和 hash；不会据此证明回答确实来自文心，也不会自动运行分析、优化或模型生成。" />
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message="无法导入" description={error} />}
    {result && <Alert style={{ marginTop: 12 }} type="success" showIcon
      message={`已保存 MANUAL_IMPORT Run ${result.run_id}`}
      description={<Space direction="vertical"><span>{result.warning}</span><code>{result.payload_hash}</code><Button onClick={() => window.location.reload()}>刷新并查看 Run 池</Button></Space>} />}
    <Form form={form} layout="vertical" onFinish={buildPreview} onValuesChange={() => { setPreview(undefined); setResult(undefined); }} style={{ marginTop: 16 }}>
      <Space wrap align="start" style={{ width: "100%" }}>
        <Form.Item label="回答对应的问题版本" name="prompt_version_id" rules={[{ required: true }]} extra="选择你实际向 AI 提问时使用的问题版本">
          <Select style={{ minWidth: 280 }} options={promptVersions.map(item => ({ value: item.prompt_version_id, label: `版本 ${item.version_number} · ${item.status === "EFFECTIVE" ? "当前生效" : "历史版本"} · ${formatBeijingDateTime(item.created_at)}` }))} />
        </Form.Item>
        <Form.Item label="回答对应的品牌资料版本" name="configuration_version_id" rules={[{ required: true }]} extra="选择观察回答时正在使用的品牌资料">
          <Select style={{ minWidth: 280 }} options={configVersions.map(item => ({ value: item.configuration_version_id, label: `版本 ${item.version_number} · ${item.status} · ${formatBeijingDateTime(item.created_at)}` }))} />
        </Form.Item>
      </Space>
      <Space wrap align="start">
        <Form.Item label="AI 平台" name="source_platform" rules={[{ required: true }]}><Select style={{ width: 180 }} disabled options={[{ value: "wenxin", label: "文心助手（人工观察）" }]} /></Form.Item>
        <Form.Item label="实际观察时间（北京时间）" name="observed_at" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item>
      </Space>
      <Form.Item label="来源页面（可选）" name="source_page_url" rules={[{ type: "url", warningOnly: true }]}><Input placeholder="实际观察页面 URL" /></Form.Item>
      <Form.Item label="完整回答原文" name="answer_text" rules={[{ required: true, min: 20, whitespace: true }]}><Input.TextArea rows={10} placeholder="粘贴完整回答，不要改写或摘要" /></Form.Item>
      <Form.Item label="引用观察状态" name="citation_observation_status" rules={[{ required: true }]}><Select options={[
        { value: "COMPLETE", label: "引用记录完整" }, { value: "CONFIRMED_NONE", label: "已确认无引用" },
        { value: "UNKNOWN", label: "引用信息未提供 / 未知" }, { value: "PARSE_FAILED", label: "引用解析失败（可能有部分 URL）" },
      ]} /></Form.Item>
      {citationStatus !== "CONFIRMED_NONE" && <Form.Item label="实际观察到的引用" name="citations_text" extra="每行一条：标题 | https://example.com；只有 URL 也可以"><Input.TextArea rows={4} /></Form.Item>}
      <Form.Item label="引用说明" name="citation_note" rules={[{ required: ["UNKNOWN", "PARSE_FAILED"].includes(citationStatus), whitespace: true }]}><Input.TextArea rows={2} placeholder="说明为何未知、缺失或解析失败" /></Form.Item>
      <Button htmlType="submit" icon={<ClipboardPaste size={16} />}>预览导入</Button>
    </Form>
    {preview && <section style={{ marginTop: 18 }} aria-label="人工导入预览">
      <Descriptions bordered size="small" column={1} title="提交前确认">
        <Descriptions.Item label="来源"><Tag>MANUAL_IMPORT</Tag> 文心助手 · <Tag color="orange">未经系统独立核实</Tag></Descriptions.Item>
        <Descriptions.Item label="问题版本">版本 {preview.promptVersion.version_number} · <code>{preview.promptVersion.snapshot_hash}</code></Descriptions.Item>
        <Descriptions.Item label="品牌资料版本">版本 {preview.configurationVersion.version_number} · <code>{preview.configurationVersion.snapshot_hash}</code></Descriptions.Item>
        <Descriptions.Item label="观察时间">{formatBeijingDateTime(String(preview.payload.observed_at))}</Descriptions.Item>
        <Descriptions.Item label="回答长度 / 引用">{String(preview.payload.answer_text).length} 字 / {preview.citationCount} 条 · {String(preview.payload.citation_observation_status)}</Descriptions.Item>
      </Descriptions>
      <Button style={{ marginTop: 12 }} type="primary" loading={busy} icon={<ShieldCheck size={16} />} onClick={submit}>确认并保存回答</Button>
    </section>}
  </section>;
}
