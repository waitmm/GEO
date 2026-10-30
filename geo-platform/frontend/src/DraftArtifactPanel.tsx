import { useEffect, useMemo, useState } from "react";
import { Alert, App as AntApp, Button, Card, Collapse, Descriptions, Form, Input, Select, Space, Tag, Typography } from "antd";
import { Copy, Download, RefreshCw } from "lucide-react";
import { request } from "./api/client";
import { BusinessMarkdown } from "./BusinessMarkdown";
import { formatBeijingDateTime } from "./time";

export type DraftArtifact = {
  artifact_version: string; artifact_id: string; parent_result_version: string;
  version_number: number; previous_artifact_version?: string | null;
  artifact_type: "HELP_DOC" | "FAQ" | string; status: string;
  title: string; body_markdown: string; evidence: Record<string, unknown>;
  qa: Record<string, unknown>; failure?: { code: string; detail: string } | null;
  artifact_hash: string; created_at: string;
};

type Feedback = {
  feedback_id: string; artifact_version: string; rating: string; suggestion: string; created_at: string;
};

const typeLabel: Record<string, string> = { HELP_DOC: "帮助文档", FAQ: "常见问题 FAQ" };
const statusLabel: Record<string, string> = {
  SUCCESS: "已完成", FAILED: "失败", NEEDS_REVIEW: "待人工核对", QUEUED: "等待生成", RUNNING: "生成中",
};
const parentLabel: Record<string, string> = {
  SUCCESS: "全部完成", PARTIAL_SUCCESS: "部分完成", FAILED: "未完成", LEGACY_SINGLE_DRAFT: "历史单稿",
};

function download(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click();
  URL.revokeObjectURL(url);
}

export function DraftArtifactPanel({ artifacts, projectId, promptId, parentStatus, regenerationEnabled, onChanged }: {
  artifacts: DraftArtifact[]; projectId: number; promptId: number; parentStatus: string;
  regenerationEnabled: boolean; onChanged: () => Promise<void>;
}) {
  const { message } = AntApp.useApp();
  const latest = useMemo(() => {
    const byId = new Map<string, DraftArtifact>();
    for (const row of artifacts) {
      const old = byId.get(row.artifact_id);
      if (!old || row.version_number > old.version_number) byId.set(row.artifact_id, row);
    }
    return [...byId.values()].sort((a, b) => a.artifact_type.localeCompare(b.artifact_type));
  }, [artifacts]);

  return <Card style={{ marginTop: 16 }} title="本次优化的内容资产"
    extra={<Tag color={parentStatus === "SUCCESS" ? "green" : parentStatus === "PARTIAL_SUCCESS" ? "orange" : undefined}>
      {parentLabel[parentStatus] || parentStatus}
    </Tag>}>
    <Alert type="info" showIcon message="每份内容独立保存和校验"
      description="帮助文档与 FAQ 共享本次冻结的诊断、策略和证据；每份稿件仍有独立状态、证据、QA、导出、反馈和重生成历史。单篇失败不会删除另一篇成果。" />
    {!regenerationEnabled && <Alert style={{ marginTop: 8 }} type="warning" showIcon
      message="单篇重新生成尚未启用"
      description="当前服务端没有获得单资产外部生成授权，因此不会创建无法执行的排队任务；查看、复制、导出和反馈不受影响。" />}
    <Space direction="vertical" size="middle" style={{ width: "100%", marginTop: 12 }}>
      {latest.map(row => <ArtifactCard key={row.artifact_version} artifact={row} projectId={projectId}
        promptId={promptId} regenerationEnabled={regenerationEnabled} onChanged={onChanged}
        notify={(kind, text) => message[kind](text)} />)}
    </Space>
  </Card>;
}

function ArtifactCard({ artifact, projectId, promptId, regenerationEnabled, onChanged, notify }: {
  artifact: DraftArtifact; projectId: number; promptId: number; onChanged: () => Promise<void>;
  regenerationEnabled: boolean;
  notify: (kind: "success" | "error", text: string) => void;
}) {
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  const query = `project_id=${projectId}&prompt_id=${promptId}`;
  useEffect(() => {
    request<Feedback[]>(`/api/v2/single-prompt/draft-artifacts/${encodeURIComponent(artifact.artifact_version)}/feedback?${query}`)
      .then(setFeedback).catch(() => setFeedback([]));
  }, [artifact.artifact_version, query]);

  async function exportOne() {
    setBusy(true);
    try {
      const file = await request<{ filename: string; content: string }>(
        `/api/v2/single-prompt/draft-artifacts/${encodeURIComponent(artifact.artifact_version)}/export?${query}`);
      download(file.filename, file.content); notify("success", "已导出当前稿件版本");
    } catch (e) { notify("error", (e as Error).message); }
    finally { setBusy(false); }
  }
  async function regenerate() {
    setBusy(true);
    try {
      await request(`/api/v2/single-prompt/draft-artifacts/${encodeURIComponent(artifact.artifact_version)}/regenerations`, {
        method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId, idempotency_key: crypto.randomUUID() }),
      });
      notify("success", "当前稿件已进入重新生成队列，其他稿件和历史版本不会改变"); await onChanged();
    } catch (e) { notify("error", (e as Error).message); }
    finally { setBusy(false); }
  }
  async function submit(values: Record<string, unknown>) {
    setBusy(true);
    try {
      const row = await request<Feedback>(
        `/api/v2/single-prompt/draft-artifacts/${encodeURIComponent(artifact.artifact_version)}/feedback`, {
          method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId, ...values }),
        });
      setFeedback(old => [row, ...old]); form.resetFields(); notify("success", "反馈已绑定当前稿件版本保存");
    } catch (e) { notify("error", (e as Error).message); }
    finally { setBusy(false); }
  }

  return <Card size="small" title={<Space wrap><span>{typeLabel[artifact.artifact_type] || artifact.artifact_type}</span>
    <Tag color={artifact.status === "SUCCESS" ? "green" : "red"}>{statusLabel[artifact.status] || artifact.status}</Tag>
    <Typography.Text type="secondary">第 {artifact.version_number} 版 · {formatBeijingDateTime(artifact.created_at)}</Typography.Text></Space>}>
    {artifact.failure && <Alert type="warning" showIcon message="稿件已保存，但未通过独立校验"
      description={`${artifact.failure.code}：${artifact.failure.detail}。正文仍可查看和反馈，但不能作为合格稿件导出。`} />}
    {artifact.body_markdown && <>
      <Typography.Title level={5}>{artifact.title}</Typography.Title>
      <BusinessMarkdown markdown={artifact.body_markdown} />
      <Space wrap>
        <Button icon={<Copy size={16} />} onClick={() => void navigator.clipboard.writeText(artifact.body_markdown)
          .then(() => notify("success", artifact.status === "SUCCESS" ? "已复制当前稿件" : "已复制未通过校验的草稿"))
          .catch(() => notify("error", "复制失败，请检查浏览器权限"))}>{artifact.status === "SUCCESS" ? "复制" : "复制未通过草稿"}</Button>
        <Button icon={<Download size={16} />} loading={busy} disabled={artifact.status !== "SUCCESS"}
          onClick={() => void exportOne()}>导出 Markdown</Button>
        <Button icon={<RefreshCw size={16} />} loading={busy} disabled={!regenerationEnabled}
          onClick={() => void regenerate()}>只重新生成这份</Button>
      </Space>
    </>}
    <Collapse style={{ marginTop: 12 }} items={[
      { key: "evidence", label: "证据与 QA", children: <Descriptions size="small" column={1}>
        <Descriptions.Item label="证据定位"><pre>{JSON.stringify(artifact.evidence, null, 2)}</pre></Descriptions.Item>
        <Descriptions.Item label="独立 QA"><pre>{JSON.stringify(artifact.qa, null, 2)}</pre></Descriptions.Item>
      </Descriptions> },
      { key: "feedback", label: `这份稿件的反馈（${feedback.length}）`, children: <>
        <Form form={form} layout="vertical" initialValues={{ adoption_status: "UNKNOWN", modification_level: "NOT_RECORDED", reason_tags: [] }} onFinish={submit}>
          <Form.Item name="rating" label="是否可用" rules={[{ required: true }]}><Select options={[
            { value: "USABLE", label: "可用" }, { value: "NEEDS_CHANGES", label: "需修改" }, { value: "UNUSABLE", label: "不可用" },
          ]} /></Form.Item>
          <Form.Item name="adoption_status" label="采用情况"><Select options={[
            { value: "ADOPTED", label: "已采用" }, { value: "PARTIALLY_ADOPTED", label: "部分采用" },
            { value: "NOT_ADOPTED", label: "未采用" }, { value: "UNKNOWN", label: "尚未决定" },
          ]} /></Form.Item>
          <Form.Item name="modification_level" label="修改量"><Select options={[
            { value: "NONE", label: "无需修改" }, { value: "LIGHT", label: "少量修改" }, { value: "MEDIUM", label: "中等修改" },
            { value: "HEAVY", label: "大量修改" }, { value: "NOT_RECORDED", label: "未记录" },
          ]} /></Form.Item>
          <Form.Item name="reason_tags" label="问题原因"><Select mode="multiple" options={[
            { value: "BRAND_ASSOCIATION", label: "品牌关联不足" }, { value: "FACTUAL_ACCURACY", label: "事实准确性" },
            { value: "STRATEGY_TOO_GENERIC", label: "策略过于泛化" }, { value: "DRAFT_QUALITY", label: "正文质量" },
            { value: "EVIDENCE_LIMITATION", label: "证据不足" }, { value: "OPERABILITY", label: "操作体验" }, { value: "OTHER", label: "其他" },
          ]} /></Form.Item>
          <Form.Item name="suggestion" label="建议"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="modification_summary" label="主要修改内容"><Input.TextArea rows={2} /></Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>保存这份稿件的反馈</Button>
        </Form>
        {feedback.map(row => <Typography.Paragraph key={row.feedback_id} type="secondary">
          {formatBeijingDateTime(row.created_at)} · {row.rating} · {row.suggestion || "未填写建议"}
        </Typography.Paragraph>)}
      </> },
    ]} />
  </Card>;
}
