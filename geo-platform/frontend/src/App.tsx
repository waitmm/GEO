import { useEffect, useMemo, useState } from "react";
import type { Key } from "react";
import {
  Alert, Button, Card, Col, Descriptions, Drawer, Empty, Form, Input, InputNumber,
  Layout, Menu, Progress, Row, Select, Space, Statistic, Table, Tag, Typography, message
} from "antd";
import { BarChart3, ExternalLink, FileText, ListChecks, Monitor, Play, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "./api/client";
import type {
  BrowserMonitorRun, BrowserMonitorRunDetail, BrowserQueueSummary, Project, Prompt, PromptCluster, RunArtifactContent, Topic,
  ValidationDashboard, ValidationPresence, ValidationSource
} from "./types";

const { Header, Sider, Content } = Layout;
const { Title, Text, Link } = Typography;
type PageKey = "validation" | "config" | "runs";

const emptyQueue: BrowserQueueSummary = {
  project_id: null, queued: 0, pending: 0, running: 0, success: 0,
  partial_success: 0, failed: 0, blocked: 0, total: 0, latest_run_id: null,
  latest_status: "", latest_stage: "", latest_error_type: ""
};

function statusTag(status: string) {
  const labels: Record<string, string> = {
    success: "成功", partial_success: "部分成功", failed: "采集失败",
    blocked: "被拦截", running: "运行中", pending: "等待中", queued: "队列中"
  };
  const colors: Record<string, string> = {
    success: "green", partial_success: "gold", failed: "red", blocked: "volcano",
    running: "processing", pending: "default", queued: "blue"
  };
  return <Tag color={colors[status]}>{labels[status] || status || "未知"}</Tag>;
}

function safeRate(n: number, d: number) {
  return d ? Math.round((n / d) * 1000) / 10 : 0;
}

function deriveDashboard(project: Project, prompts: Prompt[], runs: BrowserMonitorRun[], details: BrowserMonitorRunDetail[]): ValidationDashboard {
  const valid = runs.filter((run) => run.status === "success" || run.status === "partial_success");
  const brandRuns = valid.filter((run) => run.brand_mentioned).length;
  const recommended = valid.filter((run) => run.brand_recommendation_level > 0).length;
  const domains = new Map<string, Set<number>>();
  const urls = new Map<string, { title: string; domain: string; runs: Set<number> }>();
  details.forEach((detail) => detail.references.forEach((ref) => {
    if (ref.domain) {
      if (!domains.has(ref.domain)) domains.set(ref.domain, new Set());
      domains.get(ref.domain)!.add(detail.id);
    }
    if (ref.url) {
      if (!urls.has(ref.url)) urls.set(ref.url, { title: ref.display_title, domain: ref.domain, runs: new Set() });
      urls.get(ref.url)!.runs.add(detail.id);
    }
  }));
  const presence: ValidationPresence[] = [{
    name: project.brand_name,
    kind: "brand",
    appeared_runs: brandRuns,
    sample_runs: valid.length,
    recommended_runs: recommended,
    mentioned_runs: Math.max(0, brandRuns - recommended)
  }];
  project.competitors.forEach((competitor) => presence.push({
    name: competitor.name, kind: "competitor", appeared_runs: 0, sample_runs: valid.length
  }));
  return {
    project_id: project.id,
    sample_label: "Validation Sample",
    environment_label: "本机 · 文心网页端 · 单一采集环境",
    prompts: {
      total: prompts.length,
      executed: new Set(valid.map((run) => run.prompt_id)).size,
      clusters: new Set(prompts.map((prompt) => prompt.prompt_group).filter(Boolean)).size,
      valid_runs: valid.length,
      sample_runs: runs.length
    },
    presence,
    recommendation: {
      explicit: recommended,
      mentioned: Math.max(0, brandRuns - recommended),
      absent: Math.max(0, valid.length - brandRuns),
      sample_runs: valid.length
    },
    top_domains: [...domains].map(([value, ids]) => ({ value, run_count: ids.size })).sort((a, b) => b.run_count - a.run_count).slice(0, 8),
    top_urls: [...urls].map(([value, item]) => ({ value, title: item.title, domain: item.domain, run_count: item.runs.size })).sort((a, b) => b.run_count - a.run_count).slice(0, 8),
    quality: {
      total_runs: runs.length,
      successful_runs: valid.length,
      blocked_runs: runs.filter((run) => run.error_type?.includes("captcha") || run.error_type?.includes("blocked")).length,
      collector_failed_runs: runs.filter((run) => run.status === "failed" && !run.error_type?.includes("captcha") && !run.error_type?.includes("blocked")).length,
      complete_reference_runs: valid.filter((run) => run.reference_complete).length,
      eligible_reference_runs: valid.length,
      parsed_references: valid.reduce((sum, run) => sum + run.detected_reference_count, 0),
      resolved_urls: valid.reduce((sum, run) => sum + run.resolved_reference_count, 0)
    }
  };
}

function PresenceTable({ data }: { data: ValidationPresence[] }) {
  return <Table size="small" rowKey={(row) => `${row.kind}-${row.name}`} pagination={false} dataSource={data} columns={[
    { title: "对象", render: (_, row) => <Space><Tag color={row.kind === "brand" ? "blue" : "orange"}>{row.kind === "brand" ? "品牌" : "竞品"}</Tag><Text strong>{row.name}</Text></Space> },
    { title: "观察结果", width: 180, render: (_, row) => <><Text strong>{row.appeared_runs} / {row.sample_runs}</Text><Text type="secondary"> 次出现</Text></> },
    { title: "说明", render: (_, row) => row.sample_runs ? <Text type="secondary">观察提及率 {safeRate(row.appeared_runs, row.sample_runs)}%，样本 n={row.sample_runs}</Text> : <Text type="secondary">暂无有效样本</Text> }
  ]} />;
}

function SourceTable({ data, url }: { data: ValidationSource[]; url?: boolean }) {
  return <Table size="small" rowKey="value" pagination={false} dataSource={data} locale={{ emptyText: "尚无可聚合的引用数据" }} columns={[
    { title: url ? "引用页面" : "域名", render: (_, row) => url ? <Space direction="vertical" size={0}><Text>{row.title || row.value}</Text><Link href={row.value} target="_blank" ellipsis><ExternalLink size={12} /> {row.domain || row.value}</Link></Space> : <Text>{row.value}</Text> },
    { title: "出现 Run", dataIndex: "run_count", width: 100, render: (value) => <Tag>{value} 次</Tag> }
  ]} />;
}

export default function App() {
  const [page, setPage] = useState<PageKey>("validation");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number>();
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [clusters, setClusters] = useState<PromptCluster[]>([]);
  const [runs, setRuns] = useState<BrowserMonitorRun[]>([]);
  const [queue, setQueue] = useState<BrowserQueueSummary>(emptyQueue);
  const [selectedPrompts, setSelectedPrompts] = useState<Key[]>([]);
  const [dashboard, setDashboard] = useState<ValidationDashboard>();
  const [detail, setDetail] = useState<BrowserMonitorRunDetail>();
  const [artifact, setArtifact] = useState<RunArtifactContent>();
  const [loading, setLoading] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [promptForm] = Form.useForm();
  const [auditForm] = Form.useForm();
  const project = projects.find((item) => item.id === projectId);

  async function loadProjects() {
    const next = await api.listProjects();
    setProjects(next);
    if (!projectId && next.length) setProjectId(next[0].id);
  }

  async function loadProject(id: number) {
    setLoading(true);
    try {
      const [nextPrompts, nextRuns, nextQueue, nextTopics, nextClusters] = await Promise.all([
        api.listPrompts(id), api.listBrowserAuditRuns(id), api.getBrowserQueueSummary(id),
        api.listTopics(id), api.listPromptClusters(id)
      ]);
      setPrompts(nextPrompts);
      setRuns(nextRuns);
      setQueue(nextQueue);
      setTopics(nextTopics);
      setClusters(nextClusters);
      try {
        setDashboard(await api.getValidationDashboard(id));
        setFallback(false);
      } catch {
        const selected = projects.find((item) => item.id === id);
        const successful = nextRuns.filter((run) => run.status === "success" || run.status === "partial_success");
        const nextDetails = (await Promise.all(successful.slice(0, 40).map((run) => api.getBrowserAuditRun(run.id).catch(() => null))))
          .filter((item): item is BrowserMonitorRunDetail => Boolean(item));
        if (selected) setDashboard(deriveDashboard(selected, nextPrompts, nextRuns, nextDetails));
        setFallback(true);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadProjects().catch((error) => message.error(error.message)); }, []);
  useEffect(() => { if (projectId) loadProject(projectId).catch((error) => message.error(error.message)); }, [projectId, projects.length]);

  async function openRun(id: number) {
    setArtifact(undefined);
    setDetail(await api.getBrowserAuditRun(id));
  }

  async function openArtifact(id: number) {
    setArtifact(await api.getRunArtifactContent(id));
  }

  async function createPrompt(values: { topic?: string; prompt_group: string; prompt_text: string; importance?: number }) {
    if (!projectId) return;
    setLoading(true);
    try {
      const topicName = values.topic?.trim() || "未分类";
      let topic = topics.find((item) => item.name === topicName);
      if (!topic) {
        topic = await api.createTopic(projectId, { name: topicName, description: "", enabled: true });
      }
      let cluster = clusters.find((item) => item.topic_id === topic!.id && item.name === values.prompt_group.trim());
      if (!cluster) {
        cluster = await api.createPromptCluster(projectId, {
          topic_id: topic.id,
          name: values.prompt_group.trim(),
          sample_count: 3,
          enabled: true
        });
      }
      await api.createPrompt(projectId, {
        topic_id: topic.id,
        cluster_id: cluster.id,
        title: values.prompt_text.slice(0, 60),
        prompt_text: values.prompt_text,
        prompt_group: values.prompt_group,
        intent_type: "supplier_recommendation",
        importance: values.importance || 3,
        sample_count: 3,
        enabled: true
      });
      promptForm.resetFields();
      message.success("Prompt 已创建");
      await loadProject(projectId);
    } finally {
      setLoading(false);
    }
  }

  async function createAudit(values: { batch_name: string; collection_mode: string; run_count: number }) {
    if (!projectId || !selectedPrompts.length) return;
    setLoading(true);
    try {
      const batch = await api.createMonitoringBatch(projectId, {
        name: values.batch_name,
        platform: "wenxin",
        collection_mode: values.collection_mode,
        sample_count: values.run_count,
        status: "queued",
        notes: values.collection_mode === "single_continuous"
          ? "Validation Sample；同一文心对话连续采集，降低安全验证风险。"
          : "Collector Qualification；每个 Sample 使用独立对话上下文。"
      });
      const result = await api.createBrowserAuditTask({
        project_id: projectId,
        batch_id: batch.id,
        platform: "wenxin",
        source_type: "browser_audit",
        adapter: "wenxin_web_audit",
        question_ids: selectedPrompts.map(Number),
        run_count: values.run_count,
        sample_count: values.run_count,
        execute_now: false
      });
      message.success(`已创建审计 Batch，共排队 ${result.queued_run_count} 个 Sample Run`);
      setSelectedPrompts([]);
      await loadProject(projectId);
    } finally {
      setLoading(false);
    }
  }

  const q = dashboard?.quality;
  const referenceResolution = q ? safeRate(q.resolved_urls, q.parsed_references) : 0;
  const referenceComplete = q ? safeRate(q.complete_reference_runs, q.eligible_reference_runs) : 0;
  const recommendationRows = useMemo(() => dashboard ? [
    { key: "explicit", label: "明确推荐", count: dashboard.recommendation.explicit, color: "#1677ff" },
    { key: "mentioned", label: "一般提及", count: dashboard.recommendation.mentioned, color: "#faad14" },
    { key: "absent", label: "未出现", count: dashboard.recommendation.absent, color: "#bfbfbf" }
  ] : [], [dashboard]);

  return <Layout className="app-shell">
    <Sider width={228} className="side-nav">
      <div className="brand-block"><Title level={4}>GEO Audit Alpha</Title><Text type="secondary">AI 可见度与引用审计</Text></div>
      <Menu mode="inline" selectedKeys={[page]} onClick={({ key }) => setPage(key as PageKey)} items={[
        { key: "validation", icon: <BarChart3 size={18} />, label: "Validation Dashboard" },
        { key: "config", icon: <ListChecks size={18} />, label: "审计配置" },
        { key: "runs", icon: <Monitor size={18} />, label: "Batch / Sample Runs" }
      ]} />
    </Sider>
    <Layout>
      <Header className="topbar">
        <div><Title level={3}>{page === "validation" ? "验证看板" : page === "config" ? "审计配置" : "采集样本"}</Title><Text type="secondary">Observation · Evidence · Comparison</Text></div>
        <Space>
          <Select className="project-select" value={projectId} placeholder="选择项目" onChange={setProjectId} options={projects.map((item) => ({ label: item.name, value: item.id }))} />
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => projectId && loadProject(projectId)}>刷新</Button>
        </Space>
      </Header>
      <Content className="workspace">
        {!project || !dashboard ? <Card loading={loading}><Empty description="请选择包含采集数据的项目" /></Card> : page === "validation" ? <Space direction="vertical" size={16} className="page-stack">
          <Card size="small" className="audit-hero">
            <Row align="middle" justify="space-between" gutter={[16, 16]}>
              <Col><Space direction="vertical" size={4}><Space><Title level={4}>{project.name}</Title><Tag color="blue">{dashboard.sample_label || "Validation Sample"}</Tag></Space><Text type="secondary">{dashboard.environment_label || "单一采集环境，仅表示当前验证样本"}</Text></Space></Col>
              <Col><Alert type="info" showIcon message="以下为验证样本观察值，不代表总体品牌曝光概率。" /></Col>
            </Row>
          </Card>
          {fallback && <Alert type="warning" showIcon message="聚合接口尚未返回数据，当前看板由已有 Run 实时兼容汇总。" />}
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="Prompt" value={dashboard.prompts.total} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="已运行 Prompt" value={dashboard.prompts.executed} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="Prompt Cluster" value={dashboard.prompts.clusters} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="有效 Run" value={dashboard.prompts.valid_runs} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="总样本" value={dashboard.prompts.sample_runs} suffix="Runs" /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="URL 解析率" value={referenceResolution} suffix="%" precision={1} /></Card></Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={14}><Card title="品牌 / 竞品出现" extra={<Tag>Validation Sample · n={dashboard.prompts.valid_runs}</Tag>}><PresenceTable data={dashboard.presence} /></Card></Col>
            <Col xs={24} xl={10}><Card title="推荐 Presence" extra={<Text type="secondary">不计算排名分</Text>}>
              <Space direction="vertical" className="page-stack">
                {recommendationRows.map((row) => <div key={row.key}><Space style={{ justifyContent: "space-between", width: "100%" }}><Text>{row.label}</Text><Text strong>{row.count} / {dashboard.recommendation.sample_runs}</Text></Space><Progress percent={safeRate(row.count, dashboard.recommendation.sample_runs)} showInfo={false} strokeColor={row.color} /></div>)}
              </Space>
            </Card></Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={10}><Card title="Top Domains"><SourceTable data={dashboard.top_domains} /></Card></Col>
            <Col xs={24} xl={14}><Card title="Top URLs"><SourceTable data={dashboard.top_urls} url /></Card></Col>
          </Row>
          <Card title={<Space><ShieldCheck size={18} />Data Quality</Space>} extra={<Text type="secondary">公开采集可信度</Text>}>
            <Row gutter={[16, 16]}>
              <Col xs={12} md={4}><Statistic title="成功 Run" value={q!.successful_runs} suffix={`/ ${q!.total_runs}`} /></Col>
              <Col xs={12} md={4}><Statistic title="Blocked" value={q!.blocked_runs} /></Col>
              <Col xs={12} md={4}><Statistic title="Collector 失败" value={q!.collector_failed_runs} /></Col>
              <Col xs={12} md={4}><Statistic title="引用完整" value={referenceComplete} suffix="%" precision={1} /></Col>
              <Col xs={12} md={4}><Statistic title="已解析标题" value={q!.parsed_references} /></Col>
              <Col xs={12} md={4}><Statistic title="已解析 URL" value={q!.resolved_urls} /></Col>
            </Row>
          </Card>
        </Space> : page === "config" ? <Space direction="vertical" size={16} className="page-stack">
          <Alert
            type="info"
            showIcon
            message="Topic → Prompt Cluster → Prompt"
            description="人工维护 Topic 与 Prompt Cluster；每个 Prompt 可配置多个 Validation Sample。"
          />
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={8}>
              <Card title="新增 Prompt" extra={<Plus size={17} />}>
                <Form form={promptForm} layout="vertical" onFinish={createPrompt} initialValues={{ importance: 3 }}>
                  <Form.Item name="topic" label="Topic">
                    <Input placeholder="例如：二维码平台选择" />
                  </Form.Item>
                  <Form.Item name="prompt_group" label="Prompt Cluster" rules={[{ required: true, message: "请输入 Cluster" }]}>
                    <Input placeholder="例如：企业选型" />
                  </Form.Item>
                  <Form.Item name="prompt_text" label="Prompt" rules={[{ required: true, message: "请输入问题" }]}>
                    <Input.TextArea rows={4} placeholder="例如：企业二维码平台哪一个好？" />
                  </Form.Item>
                  <Form.Item name="importance" label="重要度">
                    <InputNumber min={1} max={5} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} icon={<Plus size={16} />}>创建 Prompt</Button>
                </Form>
              </Card>
              <Card title="创建采集 Batch" style={{ marginTop: 16 }}>
                <Form form={auditForm} layout="vertical" onFinish={createAudit} initialValues={{
                  batch_name: `${new Date().toLocaleDateString("zh-CN")} 文心基线监测`,
                  collection_mode: "single_continuous",
                  run_count: 3
                }}>
                  <Form.Item label="已选择 Prompt"><Text strong>{selectedPrompts.length}</Text><Text type="secondary"> 条</Text></Form.Item>
                  <Form.Item name="batch_name" label="Batch 名称" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="collection_mode" label="采集模式" rules={[{ required: true }]}>
                    <Select options={[
                      { value: "single_continuous", label: "同一对话连续采集（推荐）" },
                      { value: "single_independent", label: "独立对话 Qualification" }
                    ]} />
                  </Form.Item>
                  <Form.Item
                    name="run_count"
                    label="每个 Prompt 的 Sample 数"
                    extra="每个 Sample 是一条独立 Run；属于 Validation Sample，不表述为总体曝光概率。"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} disabled={!selectedPrompts.length} icon={<Play size={16} />}>
                    加入文心采集队列
                  </Button>
                </Form>
              </Card>
            </Col>
            <Col xs={24} xl={16}>
              <Card title="Topic / Cluster / Prompt" extra={<Tag>{prompts.length} Prompts</Tag>}>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  dataSource={[...prompts].sort((a, b) => `${a.topic_id}/${a.cluster_id}`.localeCompare(`${b.topic_id}/${b.cluster_id}`, "zh-CN"))}
                  rowSelection={{ selectedRowKeys: selectedPrompts, onChange: setSelectedPrompts }}
                  columns={[
                    { title: "Topic", width: 150, render: (_, row) => <Tag color="geekblue">{topics.find((item) => item.id === row.topic_id)?.name || "未分类"}</Tag> },
                    { title: "Cluster", width: 170, render: (_, row) => <Tag color="cyan">{clusters.find((item) => item.id === row.cluster_id)?.name || row.prompt_group || "默认 Cluster"}</Tag> },
                    { title: "Prompt", dataIndex: "prompt_text" },
                    { title: "重要度", dataIndex: "importance", width: 80 }
                  ]}
                />
              </Card>
              <Card title="采集队列" style={{ marginTop: 16 }} extra={queue.latest_run_id ? <Tag>最新 Run #{queue.latest_run_id}</Tag> : null}>
                <Row gutter={[12, 12]}>
                  <Col xs={8} md={4}><Statistic title="待采集" value={queue.queued + queue.pending} /></Col>
                  <Col xs={8} md={4}><Statistic title="运行中" value={queue.running} /></Col>
                  <Col xs={8} md={4}><Statistic title="成功" value={queue.success} /></Col>
                  <Col xs={8} md={4}><Statistic title="部分成功" value={queue.partial_success} /></Col>
                  <Col xs={8} md={4}><Statistic title="Blocked" value={queue.blocked} /></Col>
                  <Col xs={8} md={4}><Statistic title="失败" value={queue.failed} /></Col>
                  <Col xs={8} md={4}><Statistic title="总 Run" value={queue.total} /></Col>
                </Row>
                <Alert
                  className="worker-hint"
                  type="warning"
                  showIcon
                  message="队列需要 Worker 持续领取"
                  description={<code>cd backend; python scripts\worker_monitoring_loop.py --interval 10 --batch-size 1</code>}
                />
              </Card>
            </Col>
          </Row>
        </Space> : <Card title="Batch / Sample Runs" extra={<Tag>每行是一条 Sample Run</Tag>}>
          <Table rowKey="id" loading={loading} dataSource={runs} pagination={{ pageSize: 12 }} onRow={(row) => ({ onClick: () => openRun(row.id) })} columns={[
            { title: "Sample", dataIndex: "id", width: 90, render: (id) => `Run #${id}` },
            { title: "Prompt", dataIndex: "original_query", ellipsis: true },
            { title: "状态", dataIndex: "status", width: 110, render: statusTag },
            { title: "样本序号", dataIndex: "run_sequence", width: 100, render: (value) => `Sample ${value}` },
            { title: "品牌", width: 110, render: (_, row) => row.brand_mentioned ? <Tag color="blue">出现 {row.brand_mention_count} 次</Tag> : <Tag>未出现</Tag> },
            { title: "四层引用", width: 230, render: (_, row) => <Space size={4}><Tag>UI {row.expected_reference_count}</Tag><Tag>DOM {row.detected_reference_count}</Tag><Tag>标题 {row.detected_reference_count}</Tag><Tag color={row.resolved_reference_count === row.detected_reference_count ? "green" : "gold"}>URL {row.resolved_reference_count}</Tag></Space> },
            { title: "Evidence", width: 100, render: (_, row) => <Button size="small" onClick={(event) => { event.stopPropagation(); openRun(row.id); }}>查看</Button> }
          ]} />
        </Card>}
      </Content>
    </Layout>
    <Drawer width={760} open={Boolean(detail)} onClose={() => { setDetail(undefined); setArtifact(undefined); }} title={detail ? `Sample Run #${detail.id}` : ""}>
      {detail && <Space direction="vertical" className="page-stack" size={16}>
        <Descriptions bordered size="small" column={2} items={[
          { key: "status", label: "状态", children: statusTag(detail.status) },
          { key: "sample", label: "Sample", children: detail.run_sequence },
          { key: "duration", label: "耗时", children: `${detail.duration_ms} ms` },
          { key: "brand", label: "品牌", children: detail.brand_mentioned ? `出现 ${detail.brand_mention_count} 次` : "未出现" }
        ]} />
        <Card size="small" title="四层引用计数">
          <Row gutter={12}><Col span={6}><Statistic title="UI 声明" value={detail.expected_reference_count} /></Col><Col span={6}><Statistic title="DOM 条目" value={detail.detected_reference_count} /></Col><Col span={6}><Statistic title="解析标题" value={detail.references.filter((r) => r.display_title).length} /></Col><Col span={6}><Statistic title="解析 URL" value={detail.resolved_reference_count} /></Col></Row>
        </Card>
        <Card size="small" title="Prompt"><Text>{detail.original_query}</Text></Card>
        <Card size="small" title="回答正文"><pre className="content-preview">{detail.answer_text || "无回答正文"}</pre></Card>
        <Card size="small" title="引用详情"><Table size="small" rowKey="id" pagination={{ pageSize: 8 }} dataSource={detail.references} columns={[
          { title: "#", dataIndex: "reference_index", width: 50 }, { title: "标题", dataIndex: "display_title" },
          { title: "域名", dataIndex: "domain", width: 150 }, { title: "URL", width: 70, render: (_, row) => row.url ? <Link href={row.url} target="_blank"><ExternalLink size={15} /></Link> : <Tag color="gold">未解析</Tag> }
        ]} /></Card>
        <Card size="small" title="Evidence 证据"><Table size="small" rowKey="id" pagination={false} dataSource={detail.artifacts} columns={[
          { title: "证据类型", dataIndex: "artifact_type", render: (value) => <Space><FileText size={15} />{value}</Space> },
          { title: "文件", dataIndex: "storage_path", ellipsis: true }, { title: "大小", dataIndex: "size_bytes", width: 100 },
          { title: "操作", width: 90, render: (_, row) => <Button size="small" disabled={row.mime_type.startsWith("image/")} onClick={() => openArtifact(row.id)}>预览</Button> }
        ]} /></Card>
        {artifact && <Card size="small" title={`Evidence 预览 · ${artifact.artifact_type}`} extra={artifact.truncated ? <Tag color="gold">已截断</Tag> : <Tag color="green">完整</Tag>}><pre className="artifact-preview">{artifact.content}</pre></Card>}
      </Space>}
    </Drawer>
  </Layout>;
}
