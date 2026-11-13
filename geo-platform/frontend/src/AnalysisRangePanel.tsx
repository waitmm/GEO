import { useState } from "react";
import { Alert, Button, Checkbox, Form, Input, Select, Space, Table, Typography } from "antd";
import { CalendarRange, CheckCircle2 } from "lucide-react";
import { request } from "./api/client";
import { beijingLocalDateTimeToIso } from "./time";

function configurationBindingReason(group: any) {
  const reason = group?.project_configuration?.reason || group?.identity?.project_configuration_binding_reason;
  const labels: Record<string, string> = {
    EMPTY_RUN_SET: "没有可确认的回答",
    RUN_CONFIGURATION_LINEAGE_UNPROVEN: "历史回答缺少观察时项目配置版本",
    MIXED_PROJECT_CONFIGURATION_VERSIONS: "回答来自不同的观察时项目配置版本",
    RUN_TASK_IDENTITY_INVALID: "回答的采集身份无法验证",
    SOURCE_ANALYSIS_LINEAGE_INVALID: "来源分析的配置谱系无法验证",
    SOURCE_ANALYSIS_CONFIGURATION_INVALID: "来源分析的项目配置无效",
    MANUAL_IMPORT_LINEAGE_INVALID: "人工导入的配置谱系无法验证",
    MANUAL_IMPORT_CONFIGURATION_INVALID: "人工导入的项目配置无效",
    COLLECTION_SCHEDULE_LINEAGE_INVALID: "采集计划的配置谱系无法验证",
    COLLECTION_SCHEDULE_CONFIGURATION_INVALID: "采集计划的项目配置无效",
  };
  return labels[reason] || "无法确认观察时项目配置版本";
}

function configurationBindingLabel(group: any) {
  const configuration = group?.project_configuration;
  return configuration?.binding_status === "BOUND" && Number.isInteger(configuration.version_number)
    ? `项目配置 V${configuration.version_number}`
    : `无法确认：${configurationBindingReason(group)}`;
}

export function AnalysisRangePanel({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [form] = Form.useForm();
  const mode = Form.useWatch("mode", form) || "LAST_7_DAYS";
  const [preview, setPreview] = useState<any>();
  const [groupHash, setGroupHash] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = `/api/v2/projects/${projectId}/prompts/${promptId}/analysis-ranges`;

  async function loadPreview(values: any) {
    setBusy(true); setError(""); setPreview(undefined); setGroupHash(""); setSelectedIds([]);
    try {
      const payload: any = { mode: values.mode, run_ids: [] };
      if (values.mode === "CUSTOM") {
        payload.start_at = beijingLocalDateTimeToIso(values.start_at);
        payload.end_at = beijingLocalDateTimeToIso(values.end_at);
      } else if (values.mode === "RUN_IDS") {
        payload.run_ids = String(values.run_ids_text || "").split(/[，,\s]+/).filter(Boolean).map(Number);
        if (payload.run_ids.some((value: number) => !Number.isInteger(value) || value <= 0)) throw new Error("回答编号必须是正整数");
      }
      const value = await request<any>(base + "/preview", { method: "POST", body: JSON.stringify(payload) });
      setPreview(value);
      const first = value.groups.find((item: any) => item.prompt_version?.binding_status === "BOUND" && item.project_configuration?.binding_status === "BOUND" && item.selected_run_ids.length);
      if (first) { setGroupHash(first.group_hash); setSelectedIds(first.selected_run_ids); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function freeze() {
    const group = preview?.groups.find((item: any) => item.group_hash === groupHash);
    if (!group || !selectedIds.length || group.prompt_version?.binding_status !== "BOUND" || group.project_configuration?.binding_status !== "BOUND") return;
    setBusy(true); setError("");
    try {
      const result = await request<any>(base + "/freeze", { method: "POST", body: JSON.stringify({
        selector: preview.selector, preview_hash: preview.preview_hash, group_hash: groupHash, selected_run_ids: selectedIds,
      }) });
      const params = new URLSearchParams({ release_view: "coreV2", v2_project: String(projectId), v2_prompt: String(promptId), v2_analysis: result.analysis.analysis_id });
      window.location.assign(`/?${params}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <section id="monitor-analysis-range" aria-label="按时间范围选择分析数据">
    <Typography.Title level={4}>选择本次要分析的回答</Typography.Title>
    <Alert type="info" showIcon message="先按时间筛选，再确认具体回答"
      description="确认后，系统会自动保存本次使用的回答及其版本。以后新增采样不会改变这次分析结果。" />
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message={error} />}
    <Form form={form} layout="vertical" initialValues={{ mode: "LAST_7_DAYS" }} onFinish={loadPreview} style={{ marginTop: 16 }}>
      <Space wrap align="start">
        <Form.Item label="分析时间范围" name="mode" rules={[{ required: true }]}><Select style={{ width: 190 }} options={[
          { value: "LAST_7_DAYS", label: "最近 7 天" }, { value: "LAST_14_DAYS", label: "最近 14 天" },
          { value: "LAST_30_DAYS", label: "最近 30 天" }, { value: "CUSTOM", label: "自定义日期" }, { value: "RUN_IDS", label: "指定回答编号" },
        ]} /></Form.Item>
        {mode === "CUSTOM" && <><Form.Item label="开始（北京时间）" name="start_at" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item><Form.Item label="结束（北京时间）" name="end_at" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item></>}
      </Space>
      {mode === "RUN_IDS" && <Form.Item label="回答编号" name="run_ids_text" rules={[{ required: true, whitespace: true }]} extra="使用逗号或空格分隔"><Input placeholder="例如：101, 102, 108" /></Form.Item>}
      <Button htmlType="submit" loading={busy} icon={<CalendarRange size={16} />}>查看可用回答</Button>
      {busy && <Typography.Text aria-live="polite" type="secondary" style={{ marginLeft: 12 }}>正在按时间和版本整理可用回答…</Typography.Text>}
    </Form>

    {preview && <section style={{ marginTop: 20 }}>
      <Alert type={preview.mixed_groups ? "warning" : "success"} showIcon
        message={`找到 ${preview.total_count} 条采样，其中 ${preview.valid_count} 条可分析、${preview.invalid_count} 条失败或无正文`}
        description={preview.mixed_groups ? "这些回答来自不同的问题版本、AI 平台或采集配置，请选择其中一组，系统不会把不兼容的数据混在一起。" : "失败采样只保留在运行记录中，不会被当作品牌未提及或零引用。"} />
      <Table style={{ marginTop: 12 }} size="small" rowKey="group_hash" pagination={false} scroll={{ x: 780 }} dataSource={preview.groups} rowSelection={{
        type: "radio", selectedRowKeys: groupHash ? [groupHash] : [],
        getCheckboxProps: (row: any) => ({ disabled: row.prompt_version?.binding_status !== "BOUND" || row.project_configuration?.binding_status !== "BOUND" || !row.selected_run_ids.length }),
        onChange: keys => { const hash = String(keys[0] || ""); setGroupHash(hash); const group = preview.groups.find((item: any) => item.group_hash === hash); setSelectedIds(group?.selected_run_ids || []); },
      }} columns={[
        { title: "平台 / 采集方式", render: (_, row: any) => <>{row.identity.platform} / {row.identity.adapter === "manual_import" ? "人工导入" : row.identity.adapter}{row.identity.source_assertion_status && <><br /><Typography.Text type="warning">人工声明，平台未独立核实</Typography.Text></>}</> },
        { title: "问题版本", render: (_, row: any) => row.prompt_version?.binding_status === "BOUND" ? "已确认" : `无法确认：${row.prompt_version?.reason || row.identity.binding_reason || "历史记录缺少版本"}` },
        { title: "观察时项目配置", render: (_, row: any) => configurationBindingLabel(row) },
        { title: "回答", render: (_, row: any) => `${row.selected_run_ids.length} 条可分析 / ${row.run_ids.length} 条总计` },
        { title: "状态", render: (_, row: any) => Object.entries(row.status_counts).map(([key, value]) => `${key} ${value}`).join("；") },
      ]} />
      {groupHash && <section style={{ marginTop: 12 }}>
        <Typography.Text strong>本次使用的回答</Typography.Text>
        <Checkbox.Group style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }} value={selectedIds} onChange={values => setSelectedIds(values.map(Number))}
          options={(preview.groups.find((item: any) => item.group_hash === groupHash)?.selected_run_ids || []).map((id: number) => ({ label: `回答 #${id}`, value: id }))} />
      </section>}
      <Button style={{ marginTop: 16 }} type="primary" loading={busy} disabled={!groupHash || !selectedIds.length || preview.groups.find((item: any) => item.group_hash === groupHash)?.project_configuration?.binding_status !== "BOUND"} icon={<CheckCircle2 size={16} />} onClick={freeze}>确认使用这 {selectedIds.length} 条回答并开始分析</Button>
    </section>}
  </section>;
}
