import { useEffect, useMemo, useState } from "react";
import type { Key } from "react";
import {
  Alert, Button, Card, Col, Descriptions, Divider, Drawer, Empty, Form, Input, InputNumber,
  Layout, Menu, Modal, Popconfirm, Progress, Row, Select, Space, Statistic, Table, Tag, Typography, message
} from "antd";
import { BarChart3, ExternalLink, FileText, ListChecks, Monitor, Play, Plus, RefreshCw, Settings, ShieldCheck } from "lucide-react";
import { api } from "./api/client";
import type {
  BrowserMonitorRun, BrowserMonitorRunDetail, BrowserQueueSummary, Project, Prompt, PromptCluster, RunArtifactContent, Topic,
  ValidationDashboard, ValidationPresence, ValidationSource
} from "./types";

const { Header, Sider, Content } = Layout;
const { Title, Text, Link } = Typography;
type PageKey = "validation" | "optimization" | "config" | "runs" | "ranking" | "golden";

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

function formatDateTime(v: string | null | undefined) {
  if (!v) return "-";
  try { return new Date(v).toLocaleString("zh-CN", { hour12: false }); }
  catch { return v; }
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
    sample_label: "验证样本",
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
  const [rankingData, setRankingData] = useState<any>(null);
  const [rankingLoading, setRankingLoading] = useState(false);
  const [strategyData, setStrategyData] = useState<any>(null);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [evidencePackages, setEvidencePackages] = useState<any[]>([]);
  const [selectedPkgId, setSelectedPkgId] = useState<number | null>(null);
  const [selectedPromptId, setSelectedPromptId] = useState<number | null>(null);
  const [goldenData, setGoldenData] = useState<any>(null);
  const [goldenLoading, setGoldenLoading] = useState(false);
  const [manualUrl, setManualUrl] = useState("");
  const [manualText, setManualText] = useState("");
  const [manualHtml, setManualHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [promptForm] = Form.useForm();
  const [auditForm] = Form.useForm();
  const [projectForm] = Form.useForm();
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);
  const project = projects.find((item) => item.id === projectId);

  function openProjectModal(id?: number) {
    if (id) {
      const target = projects.find((item) => item.id === id);
      if (target) {
        projectForm.setFieldsValue({
          name: target.name,
          brand_name: target.brand_name,
          brand_aliases: target.brand_aliases.join(", "),
          website_url: target.website_url,
          industry: target.industry,
          competitors: target.competitors.map((item) => `${item.name}:${item.aliases?.join(";") || ""}:${item.website_url || ""}`).join("\n"),
        });
        setEditingProjectId(id);
      }
    } else {
      projectForm.resetFields();
      setEditingProjectId(null);
    }
    setProjectModalOpen(true);
  }

  async function deleteCurrentProject() {
    if (!editingProjectId) return;
    await api.deleteProject(editingProjectId);
    message.success("项目已删除");
    setProjectModalOpen(false);
    setEditingProjectId(null);
    if (projectId === editingProjectId) setProjectId(undefined);
    await loadProjects();
  }

  async function submitProject(values: Record<string, string>) {
    const aliases = values.brand_aliases ? values.brand_aliases.split(",").map((item: string) => item.trim()).filter(Boolean) : [];
    const compLines = values.competitors ? values.competitors.split("\n").filter((line: string) => line.trim()) : [];
    const competitors = compLines.map((line: string) => {
      const [name, aliasesStr = "", url = ""] = line.split(":");
      return { name: name.trim(), aliases: aliasesStr.split(";").map((item) => item.trim()).filter(Boolean), website_url: url.trim() };
    });
    const payload = { ...values, brand_aliases: aliases, competitors };
    if (editingProjectId) {
      const updated = await api.updateProject(editingProjectId, payload);
      message.success("项目已更新");
      if (projectId === editingProjectId) setProjectId(updated.id);
    } else {
      const created = await api.createProject(payload);
      message.success("项目已创建");
      setProjectId(created.id);
    }
    setProjectModalOpen(false);
    setEditingProjectId(null);
    await loadProjects();
  }

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
    try {
      setArtifact(await api.getRunArtifactContent(id));
    } catch (err: any) {
      message.error(err.message || "无法加载证据内容，可能文件已丢失");
    }
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
      // 将换行输入拆分为多个独立的问题，每个问题单独提问
      const lines = values.prompt_text
        .split("\n")
        .map((line: string) => line.trim())
        .filter((line: string) => line.length > 0);
      for (const line of lines) {
        await api.createPrompt(projectId, {
          topic_id: topic.id,
          cluster_id: cluster.id,
          title: line.slice(0, 60),
          prompt_text: line,
          prompt_group: values.prompt_group,
          intent_type: "supplier_recommendation",
          importance: values.importance || 3,
          sample_count: 3,
          enabled: true
        });
      }
      promptForm.resetFields();
      message.success(lines.length > 1 ? `已创建 ${lines.length} 个 Prompt` : "Prompt 已创建");
      await loadProject(projectId);
    } finally {
      setLoading(false);
    }
  }

  async function createAudit(values: { batch_name: string; collection_mode: string; run_count: number; execute_now: boolean }) {
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
        execute_now: values.execute_now
      });
      if (values.execute_now) {
        message.success(`已创建审计 Batch 并开始采集，共 ${result.queued_run_count} 个 Sample Run`);
      } else {
        message.success(`已创建审计 Batch，共排队 ${result.queued_run_count} 个 Sample Run`);
      }
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
      <div className="brand-block"><Title level={4}>GEO 决策平台</Title><Text type="secondary">生成式搜索品牌优化</Text></div>
      <Menu mode="inline" selectedKeys={[page]} onClick={({ key }) => setPage(key as PageKey)} items={[
        { key: "validation", icon: <BarChart3 size={18} />, label: "品牌监测" },
        { key: "config", icon: <ListChecks size={18} />, label: "问题配置" },
        { key: "optimization", icon: <ShieldCheck size={18} />, label: "优化策略" },
        { key: "runs", icon: <Monitor size={18} />, label: "采集记录" },
        { key: "ranking", icon: <BarChart3 size={18} />, label: "引用分析" },
        { key: "golden", icon: <ShieldCheck size={18} />, label: "Golden Case" }
      ]} />
    </Sider>
    <Layout>
      <Header className="topbar">
        <div><Title level={3}>{page === "validation" ? "品牌 AI 可见度监测" : page === "optimization" ? "证据 → 优化策略" : page === "config" ? "Prompt 与采集配置" : page === "ranking" ? "AI 引用来源分析" : page === "golden" ? "Golden Case 内容分析" : "采集记录"}</Title><Text type="secondary">观察 · 证据 · 对比</Text></div>
        <Space>
          <Select className="project-select" value={projectId} placeholder="选择项目" onChange={setProjectId} options={projects.map((item) => ({ label: item.name, value: item.id }))} />
          <Button icon={<Plus size={16} />} onClick={() => openProjectModal()}>新建项目</Button>
          <Button icon={<Settings size={16} />} onClick={() => projectId && openProjectModal(projectId)} disabled={!projectId}>编辑项目</Button>
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => projectId && loadProject(projectId)}>刷新</Button>
        </Space>
      </Header>
      <Content className="workspace">
        {!project || !dashboard ? <Card loading={loading}><Empty description="请选择包含采集数据的项目" /></Card> : page === "validation" ? <Space direction="vertical" size={16} className="page-stack">
          <Card size="small" className="audit-hero">
            <Row align="middle" justify="space-between" gutter={[16, 16]}>
              <Col><Space direction="vertical" size={4}><Space><Title level={4}>{project.name}</Title><Tag color="blue">{dashboard.sample_label || "验证样本"}</Tag></Space><Text type="secondary">{dashboard.environment_label || "单一采集环境，仅表示当前验证样本"}</Text></Space></Col>
              <Col><Alert type="info" showIcon message="以下为验证样本观察值，不代表总体品牌曝光概率。" /></Col>
            </Row>
          </Card>
          {fallback && <Alert type="warning" showIcon message="聚合接口尚未返回数据，当前看板由已有 Run 实时兼容汇总。" />}
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="配置问题数" value={dashboard.prompts.total} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="已采集" value={dashboard.prompts.executed} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="问题组" value={dashboard.prompts.clusters} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="成功采集" value={dashboard.prompts.valid_runs} /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="总采集次数" value={dashboard.prompts.sample_runs} suffix="次" /></Card></Col>
            <Col xs={12} lg={4}><Card size="small"><Statistic title="引用URL解析率" value={referenceResolution} suffix="%" precision={1} /></Card></Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={14}><Card title="品牌与竞品在 AI 回答中的出现情况" extra={<Tag>样本量 n={dashboard.prompts.valid_runs}</Tag>}><PresenceTable data={dashboard.presence} /></Card></Col>
            <Col xs={24} xl={10}><Card title="AI 推荐情况" extra={<Text type="secondary">仅统计明确推荐</Text>}>
              <Space direction="vertical" className="page-stack">
                {recommendationRows.map((row) => <div key={row.key}><Space style={{ justifyContent: "space-between", width: "100%" }}><Text>{row.label}</Text><Text strong>{row.count} / {dashboard.recommendation.sample_runs}</Text></Space><Progress percent={safeRate(row.count, dashboard.recommendation.sample_runs)} showInfo={false} strokeColor={row.color} /></div>)}
              </Space>
            </Card></Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={10}><Card title="高频域名"><SourceTable data={dashboard.top_domains} /></Card></Col>
            <Col xs={24} xl={14}><Card title="高频页面"><SourceTable data={dashboard.top_urls} url /></Card></Col>
          </Row>
          <Card title={<Space><ShieldCheck size={18} />数据质量</Space>} extra={<Text type="secondary">公开采集可信度</Text>}>
            <Row gutter={[16, 16]}>
              <Col xs={12} md={4}><Statistic title="成功采集" value={q!.successful_runs} suffix={`/ ${q!.total_runs}`} /></Col>
              <Col xs={12} md={4}><Statistic title="被拦截" value={q!.blocked_runs} /></Col>
              <Col xs={12} md={4}><Statistic title="采集失败" value={q!.collector_failed_runs} /></Col>
              <Col xs={12} md={4}><Statistic title="引用完整度" value={referenceComplete} suffix="%" precision={1} /></Col>
              <Col xs={12} md={4}><Statistic title="已解析标题" value={q!.parsed_references} /></Col>
              <Col xs={12} md={4}><Statistic title="已解析 URL" value={q!.resolved_urls} /></Col>
            </Row>
          </Card>
        </Space> : page === "optimization" ? <Space direction="vertical" size={16} className="page-stack">
          <Card size="small" title="生成证据包" extra={<Space>
            <Button size="small" onClick={async()=>{try{setEvidencePackages(await api.listEvidencePackages(projectId!));message.success("列表已刷新")}catch(e:any){message.error(e.message)}}}>刷新列表</Button>
            {selectedPrompts.length>0 && <Button type="primary" size="small" loading={loading} onClick={async()=>{
              if(!projectId){message.error("请先选择项目");return;}
              setLoading(true);
              let ok=0;const errs:string[]=[];
              for(const pid of selectedPrompts.map(Number)){
                try{await api.createEvidencePackage(projectId,{prompt_id:pid});ok++}catch(e:any){errs.push(`#${pid}:${e?.message||e}`)}
              }
              if(ok>0)message.success(`已生成 ${ok}/${selectedPrompts.length} 个证据包`);
              if(errs.length>0)message.error(`失败 ${errs.length} 个: ${errs.slice(0,3).join("; ")}`);
              if(ok>0){setEvidencePackages(await api.listEvidencePackages(projectId));}
              setLoading(false);
            }}>为选中 Prompt 生成证据包 ({selectedPrompts.length})</Button>}
          </Space>}>
            <Table size="small" rowKey="id" pagination={{pageSize:8}}
              dataSource={[...prompts].sort((a,b)=>(b.id as number)-(a.id as number))}
              rowSelection={{selectedRowKeys:selectedPrompts,onChange:setSelectedPrompts}}
              columns={[
                {title:"ID",dataIndex:"id",width:50},
                {title:"问题内容",dataIndex:"prompt_text",ellipsis:true},
                {title:"已有Run",width:70,render:(_,row:any)=>runs.filter((r:any)=>r.prompt_id===row.id).length||0},
              ]}
            />
          </Card>
          <Card title="优化策略生成" extra={<Tag color="green">V2 引擎</Tag>}>
            <Alert type="info" showIcon style={{marginBottom:12}}
              message="根据证据包数据自动分析，生成内容干预建议。策略由客观证据推导，不预设方案。"
            />
            <Space direction="vertical" style={{width:"100%"}}>
              <Text>选择证据包查看已有策略，或为新证据包生成策略。</Text>
              <Space>
                <Select placeholder="选证据包" style={{width:360}} value={selectedPkgId}
                  onChange={async(v)=>{
                    setSelectedPkgId(v);
                    if(!projectId||!v)return;
                    setStrategyLoading(true);
                    try{
                      const existing = await api.listStrategyCandidates(projectId,v);
                      if(existing.length>0){setStrategyData({decision_status:"OPTIONS_AVAILABLE",decision_capability:"CONTENT_DIRECTION_ONLY",strategy_options_count:existing.length,candidates:existing});message.success(`已加载 ${existing.length} 个已有策略`)}
                      else setStrategyData(null);
                    }catch{setStrategyData(null)}
                    finally{setStrategyLoading(false)}
                  }}
                  notFoundContent={evidencePackages?.length===0?"暂无证据包，请先在上方生成":undefined}
                  options={(evidencePackages||[]).map((p:any)=>({label:`证据包 #${p.id} ·「${p.prompt_text||'#'+(p.prompt_id||'?')}」· v${p.version}`,value:p.id}))}
                />
                <Button onClick={async()=>{try{setEvidencePackages(await api.listEvidencePackages(projectId!))}catch{}}}>刷新包列表</Button>
                <Button type="primary" loading={strategyLoading} disabled={!selectedPkgId}
                  onClick={async()=>{
                    if(!projectId||!selectedPkgId)return;
                    setStrategyLoading(true);
                    try{setStrategyData(await api.generateStrategyCandidatesV2(projectId,{evidence_package_id:selectedPkgId,max_hypotheses:3}));message.success("新策略已生成")}
                    catch(e:any){message.error(e.message)}
                    finally{setStrategyLoading(false)}
                  }}>重新生成新策略</Button>
              </Space>
            </Space>
            {!strategyData ? <Empty description="选择证据包后自动加载已有策略，或点「重新生成新策略」创建新的" /> : strategyData.decision_status === "NEEDS_MORE_EVIDENCE" ? <Alert type="warning" showIcon
              message="证据不足，无法生成策略"
              description={strategyData.missing_evidence?.length > 0
                ? (strategyData.missing_evidence as any[]).slice(0,3).map((m:any)=>m.reason||m.category).join("；")
                : "当前证据包的数据量或维度不足以支持策略生成，建议使用数据更丰富的证据包（如 Package #7）。"}
            /> : <Space direction="vertical" size={12}>
              <Alert type="success" showIcon message={<Space><Tag color="green">{strategyData.decision_status}</Tag><Tag>{strategyData.decision_capability}</Tag><Text>共 {strategyData.strategy_options_count} 个策略候选</Text></Space>} />
              {(strategyData.candidates||[]).map((c:any)=><Card key={c.id} size="small" title={<Space><Tag color="blue">#{c.id}</Tag><Text strong>{c.structured_payload?.intervention_type}</Text></Space>} extra={<Tag color={c.review_status==="PENDING_REVIEW"?"default":"green"}>{c.review_status}</Tag>}>
                <Row gutter={[12,12]}>
                  <Col xs={24} md={8}>
                    <Card size="small" title="📊 证据事实" style={{background:"#f6ffed"}}>
                      <Text>{c.structured_payload?.evidence_summary||"无"}</Text>
                      {c.structured_payload?.evidence_fact_ids?.length>0 && <div style={{marginTop:8}}><Text type="secondary">引用事实ID: {(c.structured_payload.evidence_fact_ids as string[]).join(", ")}</Text></div>}
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="🔍 推断" style={{background:"#fff7e6"}}>
                      {(c.structured_payload?.inferences||[]).length>0
                        ? (c.structured_payload.inferences as any[]).map((inf:any)=><Alert key={inf.inference_id} type="warning" style={{marginBottom:4}} message={<Text>{inf.statement}</Text>} />)
                        : <Text type="secondary">基于当前证据推导的有限判断</Text>}
                      <div style={{marginTop:8}}><Text strong>推断原因：</Text><Text>{c.structured_payload?.hypothesized_cause||"-"}</Text></div>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small" title="🎯 策略建议" style={{background:"#e6f7ff"}}>
                      <Descriptions size="small" column={1} items={[
                        {key:"type",label:"干预类型",children:<Tag color="blue">{c.structured_payload?.intervention_type||"-"}</Tag>},
                        {key:"plat",label:"目标平台",children:<Tag color={c.structured_payload?.target_platform==="UNRESOLVED"?"orange":"blue"}>{c.structured_payload?.target_platform||"未知"}</Tag>},
                        {key:"ct",label:"内容类型",children:<Tag>{c.structured_payload?.target_content_type||"-"}</Tag>},
                        {key:"fit",label:"证据匹配度 / 执行可行性",children:<Space><Tag>{c.structured_payload?.evidence_fit||"-"}</Tag><Tag>{c.structured_payload?.execution_feasibility||"未评估"}</Tag></Space>},
                      ]}/>
                      {c.structured_payload?.recommended_action && typeof c.structured_payload.recommended_action === "object"
                        ? <Space direction="vertical" size={4} style={{marginTop:8}}>
                            <Text strong>内容方向：</Text><Text>{(c.structured_payload.recommended_action as any).content_direction||"-"}</Text>
                            <Text strong>平台方向：</Text><Text>{(c.structured_payload.recommended_action as any).platform_direction||"-"}</Text>
                            <Text strong>资产方向：</Text><Text>{(c.structured_payload.recommended_action as any).asset_direction||"-"}</Text>
                          </Space>
                        : <Text>{c.structured_payload?.recommended_action||"-"}</Text>}
                    </Card>
                  </Col>
                </Row>
              </Card>)}
              <Button icon={<RefreshCw size={14}/>} loading={strategyLoading} onClick={async()=>{
                setStrategyLoading(true);
                try{setStrategyData(await api.generateStrategyCandidatesV2(projectId!,{evidence_package_id:selectedPkgId!,max_hypotheses:3}));message.success("已刷新")}
                catch(e:any){message.error(e.message)}
                finally{setStrategyLoading(false)}
              }}>重新生成</Button>
            </Space>}
          </Card>
        </Space> : page === "config" ? <Space direction="vertical" size={16} className="page-stack">
          <Alert
            type="info"
            showIcon
            message="管理 AI 搜索问题，按主题和问题簇组织"
            description="同一用户意图可以有多个变体问法，每次独立采集验证。"
          />
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={8}>
              <Card title="新增 Prompt" extra={<Plus size={17} />}>
                <Form form={promptForm} layout="vertical" onFinish={createPrompt} initialValues={{ importance: 3 }}>
                  <Form.Item name="topic" label="主题">
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
                  run_count: 3,
                  execute_now: true
                }}>
                  <Form.Item label="已选 Prompt"><Text strong>{selectedPrompts.length}</Text><Text type="secondary"> 条</Text></Form.Item>
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
                  <Form.Item name="execute_now" valuePropName="checked">
                    <label><input type="checkbox" style={{ marginRight: 8 }} />创建后立即执行</label>
                  </Form.Item>
                  <Space>
                    <Button type="primary" htmlType="submit" loading={loading} disabled={!selectedPrompts.length} icon={<Play size={16} />}>
                      创建并采集
                    </Button>
                    <Button loading={loading} disabled={!selectedPrompts.length} onClick={() => {
                      auditForm.setFieldsValue({ execute_now: false });
                      setTimeout(() => auditForm.submit(), 0);
                    }}>
                      仅加入队列
                    </Button>
                  </Space>
                </Form>
              </Card>
            </Col>
            <Col xs={24} xl={16}>
              <Card title="问题列表" extra={<Space><Tag>{prompts.length} 条</Tag>{selectedPrompts.length>0 && <Popconfirm title={`确定删除选中的 ${selectedPrompts.length} 个 Prompt？`} onConfirm={async()=>{
                try{await api.batchDeletePrompts(projectId!,selectedPrompts.map(Number));message.success(`已删除`);setSelectedPrompts([]);loadProject(projectId!)}
                catch(e:any){message.error(e.message)}
              }}><Button danger size="small">批量删除 ({selectedPrompts.length})</Button></Popconfirm>}</Space>}>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  dataSource={[...prompts].sort((a, b) => `${a.topic_id}/${a.cluster_id}`.localeCompare(`${b.topic_id}/${b.cluster_id}`, "zh-CN"))}
                  rowSelection={{ selectedRowKeys: selectedPrompts, onChange: setSelectedPrompts }}
                  columns={[
                    { title: "主题", width: 120, render: (_, row) => <Tag color="geekblue">{topics.find((item) => item.id === row.topic_id)?.name || "未分类"}</Tag> },
                    { title: "问题组", width: 120, render: (_, row) => <Tag color="cyan">{clusters.find((item) => item.id === row.cluster_id)?.name || row.prompt_group || "-"}</Tag> },
                    { title: "问题内容", dataIndex: "prompt_text", ellipsis: true },
                    { title: "操作", width: 80, render: (_, row) => <Popconfirm title="确定删除？" onConfirm={async()=>{
                      try{await api.deletePrompt(projectId!,row.id);message.success("已删除");loadProject(projectId!)}
                      catch(e:any){message.error(e.message)}
                    }}><Button danger size="small">删除</Button></Popconfirm> }
                  ]}
                />
              </Card>
              <Card title="采集队列" style={{ marginTop: 16 }} extra={
                <Space>
                  {queue.latest_run_id ? <Tag>最新 Run #{queue.latest_run_id}</Tag> : null}
                  <Button
                    type="primary"
                    size="small"
                    icon={<Play size={14} />}
                    loading={loading}
                    disabled={queue.queued + queue.pending === 0}
                    onClick={async () => {
                      setLoading(true);
                      try {
                        const result = await api.executeQueuedRuns(projectId!);
                        message.success(`已执行 ${result.executed} 个 Run`);
                        await loadProject(projectId!);
                      } catch (err: any) { message.error(err.message); }
                      finally { setLoading(false); }
                    }}
                  >
                    一键执行队列
                  </Button>
                </Space>
              }>
                <Row gutter={[12, 12]}>
                  <Col xs={8} md={4}><Statistic title="待采集" value={queue.queued + queue.pending} /></Col>
                  <Col xs={8} md={4}><Statistic title="运行中" value={queue.running} /></Col>
                  <Col xs={8} md={4}><Statistic title="成功" value={queue.success} /></Col>
                  <Col xs={8} md={4}><Statistic title="部分成功" value={queue.partial_success} /></Col>
                  <Col xs={8} md={4}><Statistic title="Blocked" value={queue.blocked} /></Col>
                  <Col xs={8} md={4}><Statistic title="失败" value={queue.failed} /></Col>
                  <Col xs={8} md={4}><Statistic title="总 Run" value={queue.total} /></Col>
                </Row>
              </Card>
            </Col>
          </Row>
        </Space> : page === "ranking" ? <Space direction="vertical" size={16} className="page-stack">
          <Card title={<Space>AI 引用来源排名<Tag color="blue">scoring.v0</Tag></Space>} extra={<Text type="secondary">证据包 #{rankingData?.package_id} · {rankingData?.scoring_spec_fingerprint?.slice(0,8)}</Text>}>
            <Alert type="info" showIcon style={{marginBottom:12}}
              message={<span><strong>引用来源排名</strong> — 展示当前证据包内各域名/平台的相对引用信号强度。<strong>不代表</strong>平台有效性、成功概率或因果关系。分数仅在同一证据包内可比较。</span>}
            />
            <Space style={{marginBottom:12}}>
              <Button type="primary" loading={rankingLoading} onClick={()=>{
                setRankingLoading(true);
                api.getCitationRanking(7).then(data=>{setRankingData(data);message.success("已加载")}).catch(e=>{message.error(String(e.message||e))}).finally(()=>setRankingLoading(false));
              }}>加载排名数据</Button>
              {rankingData && <Button onClick={()=>setRankingData(null)}>清除</Button>}
            </Space>
            {!rankingData ? <Empty description="点击「加载排名数据」查看 Package #7 的引用证据排名" /> : <Space direction="vertical" size={12}>
              <Row gutter={12}>
                <Col span={8}><Statistic title="引用总数" value={rankingData.total_references}/></Col>
                <Col span={8}><Statistic title="独立域名" value={rankingData.unique_domains}/></Col>
                <Col span={8}><Statistic title="独立 URL" value={rankingData.unique_urls_global}/></Col>
              </Row>
              <Card size="small" title={<Space>域名排名<Tag>范围={rankingData.ranking_scope}</Tag></Space>}>
                <Table size="small" rowKey="source_domain" pagination={{pageSize:10}} dataSource={rankingData.domain_ranking||[]}
                  columns={[
                    {title:"排名",dataIndex:"evidence_rank_raw",width:55},
                    {title:"域名",dataIndex:"source_domain",width:170},
                    {title:"平台",width:90,render:(_:any,r:any)=><Tag>{r.inferred_platform}</Tag>},
                    {title:"分数",width:65,render:(_:any,r:any)=>(r.raw_evidence_score as number)?.toFixed(1)},
                    {title:"置信度",width:60,render:(_:any,r:any)=><Tag color={r.confidence==="HIGH"?"green":r.confidence==="MEDIUM"?"gold":"orange"}>{r.confidence_zh||r.confidence}</Tag>},
                    {title:"次数",dataIndex:"citation_occurrence_count",width:55},
                    {title:"独立URL",dataIndex:"unique_citation_urls",width:50},
                    {title:"Top1占比",width:55,render:(_:any,r:any)=>r.top1_url_share?Math.round((r.top1_url_share as number)*100)+"%":"-"},
                  ]}
                  expandable={{expandedRowRender:(row:any)=><Space direction="vertical" size={6}>
                    <Text strong>因子分解（总分：{row._decomposition?.total_score}）</Text>
                    {(Object.entries(row._decomposition||{})as[string,any][]).filter(([k])=>k!=="total_score").map(([fn,fd])=>(
                      <Card key={fn} size="small" title={<Space><Text strong>{fd.factor_name_zh||fn}</Text><Tag color={fd.factor_status==="ACTIVE"?"green":fd.factor_status==="DIAGNOSTIC_ONLY"?"gold":"default"}>{fd.factor_status_zh||fd.factor_status}</Tag></Space>}>
                        <Row gutter={[8,4]}>
                          <Col span={6}><Text type="secondary">配置权重: {((fd.configured_weight as number)*100).toFixed(0)}%</Text></Col>
                          <Col span={6}><Text type="secondary">实际权重: {((fd.active_weight as number)*100).toFixed(1)}%</Text></Col>
                          <Col span={6}><Text type="secondary">贡献: {(fd.weighted_contribution as number)?.toFixed(3)}</Text></Col>
                          <Col span={6}><Text>原始: {fd.raw_factor_score}</Text></Col>
                        </Row>
                        <Space wrap>{(fd.primary_dimensions_zh||fd.primary_dimensions||[])?.map((d:string)=><Tag key={d} color="blue">{d}</Tag>)}
                        {(fd.auxiliary_dimensions_zh||fd.auxiliary_dimensions||[])?.map((d:string)=><Tag key={d} color="gold">{d}</Tag>)}
                        {(fd.excluded_dimensions_zh||fd.excluded_dimensions||[])?.map((d:string)=><Tag key={d} color="default">{d}</Tag>)}</Space>
                        {fd.reason?<Alert type={fd.factor_status==="DIAGNOSTIC_ONLY"?"warning":"info"} style={{marginTop:4}} message={fd.reason}/>:null}
                      </Card>
                    ))}
                  </Space>}}
                />
              </Card>
              <Card size="small" title={<Space>平台排名<Tag color="gold">{rankingData.platform_ranking?.[0]?.platform_semantics_zh||"基于域名推断"}</Tag></Space>}>
                <Table size="small" rowKey="inferred_platform" pagination={false} dataSource={rankingData.platform_ranking||[]}
                  columns={[
                    {title:"排名",dataIndex:"platform_rank",width:55},
                    {title:"平台",dataIndex:"inferred_platform",width:100},
                    {title:"分数",width:65,render:(_:any,r:any)=>(r.avg_raw_evidence_score as number)?.toFixed(1)},
                    {title:"域名数",dataIndex:"domain_count",width:65},
                    {title:"引用次数",dataIndex:"total_citation_occurrences",width:90},
                  ]}
                  expandable={{expandedRowRender:(row:any)=><Space direction="vertical" size={4}>
                    <Text strong>构成域名</Text>
                    {(row.domains as string[])?.map((d:string)=><Tag key={d} color="blue">{d}</Tag>)}
                  </Space>}}
                />
              </Card>
              <Card size="small" title="已知局限">
                {(rankingData.known_limitations||[]).map((lim:any)=><Alert key={lim.code} type="warning" showIcon style={{marginBottom:6}}
                  message={<Space><Tag>{lim.code}</Tag><Text strong>{lim.title}</Text></Space>} description={lim.description}/>)}
              </Card>
              <Button icon={<RefreshCw size={14}/>} loading={rankingLoading} onClick={()=>{
                setRankingLoading(true);
                api.getCitationRanking(7).then(data=>{setRankingData(data);message.success("已刷新")}).catch(e=>{message.error(String(e.message||e))}).finally(()=>setRankingLoading(false));
              }}>刷新</Button>
            </Space>}
          </Card>
        </Space> : page === "golden" ? <Space direction="vertical" size={16} className="page-stack">
          <Card title="Golden Case 内容分析" extra={<Space>
            <Select placeholder="选Prompt" style={{width:220}} value={selectedPromptId} onChange={async(v)=>{
              setSelectedPromptId(v);
              const promptRuns = runs.filter((r:any)=>r.prompt_id===v&&(r.status==="success"||r.status==="partial_success"));
              if(promptRuns.length===0){message.warning("该Prompt没有可用Run");return;}
              setGoldenLoading(true);
              const runIds = promptRuns.map((r:any)=>r.id).join(",");
              const runIdList = promptRuns.map((r:any)=>r.id);
              // Auto-extract claims if not yet extracted
              try{
                const existing = await (await fetch(`/api/optimization/golden-case/claims?run_ids=${runIds}`)).json();
                if(!existing||existing.length===0){
                  await fetch("/api/optimization/golden-case/extract-claims",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({run_ids:runIdList})});
                }
              }catch{}
              try{
                const [s, nm, claims, audit, docs] = await Promise.all([
                  (await fetch("/api/optimization/golden-case/summary")).json(),
                  (await fetch(`/api/optimization/golden-case/need-map-validated?run_ids=${runIds}`)).json(),
                  (await fetch(`/api/optimization/golden-case/claims?run_ids=${runIds}`)).json(),
                  (await fetch("/api/optimization/golden-case/url-audit")).json(),
                  (await fetch(`/api/optimization/golden-case/documents?run_ids=${runIds}`)).json(),
                ]);
                setGoldenData({summary:s, needMap:nm, claims, urlAudit:audit, docs, promptId:v, runIds:runIds});
              }catch(e:any){message.error(e.message)}
              finally{setGoldenLoading(false)}
            }}
              options={[...new Map(runs.filter((r:any)=>r.status==="success"||r.status==="partial_success").map((r:any)=>[r.prompt_id,{id:r.prompt_id,text:r.original_query}])).values()].map((p:any)=>({label:`#${p.id} ${p.text}`,value:p.id}))}
            />
            <Tag color="orange">CITATION_ONLY</Tag>
            <Button type="primary" loading={goldenLoading} disabled={!selectedPromptId} onClick={async()=>{
              if(!goldenData?.runIds)return;
              setGoldenLoading(true);
              try{
                const [s, nm, claims, audit, docs] = await Promise.all([
                  (await fetch("/api/optimization/golden-case/summary")).json(),
                  (await fetch(`/api/optimization/golden-case/need-map-validated?run_ids=${goldenData.runIds}`)).json(),
                  (await fetch(`/api/optimization/golden-case/claims?run_ids=${goldenData.runIds}`)).json(),
                  (await fetch("/api/optimization/golden-case/url-audit")).json(),
                  (await fetch(`/api/optimization/golden-case/documents?run_ids=${goldenData.runIds}`)).json(),
                ]);
                setGoldenData({...goldenData, summary:s, needMap:nm, claims, urlAudit:audit, docs});
              }catch(e:any){message.error(e.message)}
              finally{setGoldenLoading(false)}
            }}>加载数据</Button>
          </Space>}>
            <Alert type="warning" showIcon style={{marginBottom:12}} message="12次采样答案内容一致（同一Prompt/模型/会话），Claims 会重复出现。各Run可独立审核，也可只审一个Run后批量应用。第三方平台抓取受限，仅有百度系部分页面成功。Candidate↔Citation URL重叠约3%，负样本不可用。" />
            {!goldenData ? <Empty description="点击「加载全部数据」开始" /> : <Space direction="vertical" size={12}>
              <Row gutter={12}>
                <Col span={4}><Statistic title="Claims总数" value={goldenData.summary?.answer_claims}/></Col>
                <Col span={4}><Statistic title="已审核" value={goldenData.summary?.claims_reviewed||goldenData.needMap?.reviewed||0}/></Col>
                <Col span={4}><Statistic title="确认" value={goldenData.needMap?.confirmed||0}/></Col>
                <Col span={4}><Statistic title="修正" value={goldenData.needMap?.refined||0}/></Col>
                <Col span={4}><Statistic title="错误" value={goldenData.needMap?.mislabeled||0}/></Col>
                <Col span={4}><Statistic title="模糊" value={goldenData.needMap?.ambiguous||0}/></Col>
              </Row>
              {/* Source Documents + Manual Capture (merged) */}
              <Card size="small" title="引用资料" extra={<Space>
                {goldenData?.docs?.length < 5 && goldenData?.runIds && <Button size="small" type="primary" loading={goldenLoading} onClick={async()=>{
                  setGoldenLoading(true);
                  try{
                    const runIdList = (goldenData.runIds as string).split(",").map(Number);
                    message.loading({content:"正在使用浏览器抓取引用页面...",duration:0,key:"acquire"});
                    await fetch("/api/optimization/golden-case/acquire",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({run_ids:runIdList})});
                    message.destroy("acquire");
                    const dd=await(await fetch(`/api/optimization/golden-case/documents?run_ids=${goldenData.runIds}`)).json();
                    setGoldenData({...goldenData, docs:dd});
                    message.success(`抓取完成，共 ${dd.length} 条`);
                  }catch(e:any){message.destroy("acquire");message.error(e.message)}
                  finally{setGoldenLoading(false)}
                }}>抓取引用资料</Button>}
                <Button size="small" onClick={async()=>{
                  try{setGoldenData({...goldenData, docs:await (await fetch(`/api/optimization/golden-case/documents?run_ids=${goldenData?.runIds||""}`)).json()})}
                  catch(e:any){message.error(e.message)}
                }}>刷新</Button>
              </Space>}>
                <Row gutter={12} style={{marginBottom:8}}>
                  <Col span={8}><Tag color="green">成功: {goldenData?.docs?.filter((d:any)=>d.fetch_status==="SUCCESS").length||0}</Tag></Col>
                  <Col span={8}><Tag color="gold">部分: {goldenData?.docs?.filter((d:any)=>d.fetch_status==="PARTIAL").length||0}</Tag></Col>
                  <Col span={8}><Tag color="red">待补: {goldenData?.docs?.filter((d:any)=>d.fetch_status!=="SUCCESS"&&d.fetch_status!=="PARTIAL").length||0}</Tag></Col>
                </Row>
                {goldenData.docs && <Table size="small" rowKey="id" pagination={{pageSize:8}} dataSource={goldenData.docs} columns={[
                  {title:"状态",width:60,render:(_,r:any)=><Tag color={r.fetch_status==="SUCCESS"?"green":r.fetch_status==="PARTIAL"?"gold":"red"}>{r.fetch_status==="SUCCESS"?"成功":r.fetch_status==="PARTIAL"?"部分":"失败"}</Tag>},
                  {title:"域名",dataIndex:"domain",width:100},
                  {title:"URL/标题",ellipsis:true,render:(_,r:any)=><a href={r.url} target="_blank" rel="noreferrer" style={{fontSize:12}}>{r.title||r.url}</a>},
                  {title:"字数",width:60,render:(_,r:any)=><Tag>{r.clean_text_len||0}</Tag>},
                  {title:"补录",width:70,render:(_,r:any)=>r.fetch_status!=="SUCCESS"?<Button size="small" onClick={()=>setManualUrl(r.url)}>补录</Button>:null},
                ]} />}
                <Divider />
                <Input placeholder="页面URL" value={manualUrl} onChange={e=>setManualUrl(e.target.value)} style={{width:"100%",marginBottom:6}}/>
                <Input.TextArea value={manualText} onChange={e=>setManualText(e.target.value)} rows={4} placeholder="粘贴正文..." />
                <Input.TextArea value={manualHtml} onChange={e=>setManualHtml(e.target.value)} rows={4} placeholder="或粘贴HTML源码..." style={{marginTop:6}}/>
                <Button type="primary" style={{marginTop:6}} onClick={async()=>{
                  if(!manualUrl){message.warning("请输入URL");return;}
                  if(!manualText&&!manualHtml){message.warning("请输入正文或HTML源码");return;}
                  const body:any={url:manualUrl,source_type:"CITED"};
                  if(manualHtml)body.raw_html=manualHtml;
                  if(manualText)body.clean_text=manualText;
                  await fetch("/api/optimization/golden-case/documents/manual",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
                  message.success("已录入");
                  setManualUrl("");setManualText("");setManualHtml("");
                  setGoldenData({...goldenData, docs:await (await fetch(`/api/optimization/golden-case/documents?run_ids=${goldenData?.runIds||""}`)).json()});
                }}>录入</Button>
              </Card>
              {/* URL Audit */}
              {goldenData.urlAudit && <Card size="small" title="URL 身份审计">
                <Descriptions size="small" bordered column={2}>
                  <Descriptions.Item label="原始URL重叠">{goldenData.urlAudit.raw?.overlap_rate}</Descriptions.Item>
                  <Descriptions.Item label="规范化后重叠">{goldenData.urlAudit.normalized?.overlap_rate}</Descriptions.Item>
                  <Descriptions.Item label="资格判定" span={2}><Tag color="orange">{goldenData.urlAudit.eligibility}</Tag> — {goldenData.urlAudit.note}</Descriptions.Item>
                </Descriptions>
              </Card>}
              {/* Answer Need Map */}
              {goldenData.needMap?.validated_needs && <Card size="small" title="AI 信息需求图谱（人工验证后）">
                <Table size="small" rowKey="need_name" pagination={false} dataSource={goldenData.needMap.validated_needs||[]} columns={[
                  {title:"信息需求",dataIndex:"need_name",width:100},
                  {title:"规则次数",dataIndex:"rule_count",width:70},
                  {title:"人工确认",dataIndex:"human_count",width:70},
                  {title:"Run覆盖",dataIndex:"run_coverage",width:70},
                ]} />
              </Card>}
              {/* Claims Review Table */}
              <Card size="small" title="Answer Claims 审核">
                <Table size="small" rowKey="id" pagination={{pageSize:15}}
                  dataSource={(goldenData.claims||[]).slice(0,60)}
                  columns={[
                    {title:"Run",dataIndex:"run_id",width:50},
                    {title:"#",dataIndex:"claim_index",width:35},
                    {title:"内容",dataIndex:"raw_text",ellipsis:true,render:(v:string)=><Text style={{fontSize:12}}>{v}</Text>},
                    {title:"分类",width:75,render:(_,r:any)=><Tag>{r.claim_type||"-"}</Tag>},
                    {title:"审核",width:70,render:(_,r:any)=><Tag color={r.review_status==="CONFIRMED"?"green":r.review_status==="REFINED"?"blue":r.review_status==="MISLABELED"?"red":r.review_status==="AMBIGUOUS"?"orange":"default"}>{r.review_status==="CONFIRMED"?"已确认":r.review_status==="REFINED"?"已修正":r.review_status==="MISLABELED"?"分类错误":r.review_status==="AMBIGUOUS"?"存在歧义":"待审核"}</Tag>},
                    {title:"操作",width:120,render:(_,r:any)=><Space size={1}>
                      <Button size="small" onClick={async()=>{
                        await fetch(`/api/optimization/golden-case/claims/${r.id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:"CONFIRMED",human_labels:[r.claim_type],reviewer:"human"})});
                        message.success("已确认");
                        setGoldenData({...goldenData,claims:goldenData.claims.map((c:any)=>c.id===r.id?{...c,review_status:"CONFIRMED"}:c)});
                      }}>确认</Button>
                      <Button size="small" danger onClick={async()=>{
                        await fetch(`/api/optimization/golden-case/claims/${r.id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:"MISLABELED",human_labels:[],reviewer:"human"})});
                        message.success("已标记错误");
                        setGoldenData({...goldenData,claims:goldenData.claims.map((c:any)=>c.id===r.id?{...c,review_status:"MISLABELED"}:c)});
                      }}>错误</Button>
                    </Space>},
                  ]}
                />
              </Card>
              <Alert type="info" showIcon message={<span><strong>当前状态</strong>：规则分类显示「操作步骤」为最高频信息需求（144/180 claims）。该结论正在进行人工验证。引用正文证据仍不足，品牌 /card 尚未完成同口径分析。<strong>策略继续保持暂缓决策（DEFERRED）</strong>，待 Passage Evidence 与 Brand Asset Evidence 补齐后重新评估。</span>} />
            </Space>}
          </Card>
        </Space> : <Card title="采集记录" extra={<Tag>每行是一次独立采样</Tag>}>
          <Table rowKey="id" loading={loading} dataSource={runs} pagination={{ pageSize: 12 }} onRow={(row) => ({ onClick: () => openRun(row.id) })} columns={[
            { title: "编号", dataIndex: "id", width: 70, render: (id) => `#${id}` },
            { title: "采集时间", width: 150, render: (_, row: any) => formatDateTime(row.finished_at || row.started_at || row.created_at) },
            { title: "问题", dataIndex: "original_query", ellipsis: true },
            { title: "状态", dataIndex: "status", width: 100, render: statusTag },
            { title: "样本", dataIndex: "run_sequence", width: 70, render: (value) => `第${value}次` },
            { title: "品牌", width: 110, render: (_, row) => row.brand_mentioned ? <Tag color="blue">出现 {row.brand_mention_count} 次</Tag> : <Tag>未出现</Tag> },
            { title: "引用解析", width: 230, render: (_, row) => <Space size={4}><Tag>界面 {row.expected_reference_count}</Tag><Tag>结构 {row.detected_reference_count}</Tag><Tag>标题 {row.detected_reference_count}</Tag><Tag color={row.resolved_reference_count === row.detected_reference_count ? "green" : "gold"}>URL {row.resolved_reference_count}</Tag></Space> },
            { title: "详情", width: 80, render: (_, row) => <Button size="small" onClick={(event) => { event.stopPropagation(); openRun(row.id); }}>查看</Button> }
          ]} />
        </Card>}
      </Content>
    </Layout>
    <Modal
      title={editingProjectId ? "编辑项目" : "新建项目"}
      open={projectModalOpen}
      onCancel={() => { setProjectModalOpen(false); setEditingProjectId(null); }}
      footer={null}
      width={640}
      destroyOnClose
    >
      <Form form={projectForm} layout="vertical" onFinish={submitProject} initialValues={{ region: "CN", language: "zh-CN" }}>
        <Form.Item name="name" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}>
          <Input placeholder="例如：八木屋二维码品牌监测" />
        </Form.Item>
        <Form.Item name="brand_name" label="品牌名称" rules={[{ required: true, message: "请输入品牌名称" }]}>
          <Input placeholder="例如：八木屋" />
        </Form.Item>
        <Form.Item name="brand_aliases" label="品牌别名（逗号分隔）">
          <Input placeholder="例如：八木屋二维码, Bamuwu" />
        </Form.Item>
        <Form.Item name="website_url" label="品牌官网">
          <Input placeholder="https://www.bamuwu.com" />
        </Form.Item>
        <Form.Item name="industry" label="行业">
          <Input placeholder="例如：二维码/企业服务" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="region" label="地区"><Input placeholder="CN" /></Form.Item></Col>
          <Col span={12}><Form.Item name="language" label="语言"><Input placeholder="zh-CN" /></Form.Item></Col>
        </Row>
        <Form.Item
          name="competitors"
          label="竞品（每行一个，格式：名称:别名1;别名2:官网URL）"
          extra="示例：草料二维码:草料;cli.im:https://cli.im"
        >
          <Input.TextArea rows={5} placeholder="草料二维码:草料;cli.im:https://cli.im&#10;二维斑马:二维斑马二维码:&#10;微微二维码::" />
        </Form.Item>
        <Space style={{ justifyContent: "flex-end", width: "100%" }}>
          {editingProjectId && (
            <Popconfirm title="确定删除该项目？所有数据将丢失" onConfirm={deleteCurrentProject} okText="确定删除" cancelText="取消">
              <Button danger>删除项目</Button>
            </Popconfirm>
          )}
          <Button onClick={() => { setProjectModalOpen(false); setEditingProjectId(null); }}>取消</Button>
          <Button type="primary" htmlType="submit">{editingProjectId ? "保存" : "创建"}</Button>
        </Space>
      </Form>
    </Modal>
    <Drawer width={760} open={Boolean(detail)} onClose={() => { setDetail(undefined); setArtifact(undefined); }} title={detail ? `采样详情 #${detail.id}` : ""}>
      {detail && <Space direction="vertical" className="page-stack" size={16}>
        <Descriptions bordered size="small" column={2} items={[
          { key: "status", label: "状态", children: statusTag(detail.status) },
          { key: "sample", label: "轮次", children: detail.run_sequence },
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
        <Card size="small" title="证据"><Table size="small" rowKey="id" pagination={false} dataSource={detail.artifacts} columns={[
          { title: "证据类型", dataIndex: "artifact_type", render: (value) => <Space><FileText size={15} />{value}</Space> },
          { title: "文件", dataIndex: "storage_path", ellipsis: true }, { title: "大小", dataIndex: "size_bytes", width: 100 },
          { title: "操作", width: 90, render: (_, row) => <Button size="small" disabled={(row.mime_type || "").startsWith("image/")} onClick={() => openArtifact(row.id)}>预览</Button> }
        ]} /></Card>
        {artifact && <Card size="small" title={`Evidence 预览 · ${artifact.artifact_type}`} extra={artifact.truncated ? <Tag color="gold">已截断</Tag> : <Tag color="green">完整</Tag>}><pre className="artifact-preview">{artifact.content}</pre></Card>}
      </Space>}
    </Drawer>
  </Layout>;
}
