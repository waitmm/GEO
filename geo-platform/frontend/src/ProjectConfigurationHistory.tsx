import { useEffect, useState } from "react";
import { Alert, Button, Descriptions, Empty, Select, Space, Spin, Tag } from "antd";
import { request } from "./api/client";
import { projectConfigurationVersionPath } from "./projectConfiguration";
import { formatBeijingDateTime } from "./time";

type Competitor = { name?: string; aliases?: string[]; website_url?: string };
type ConfigurationSnapshot = {
  brand_name?: string;
  brand_aliases?: string[];
  website_url?: string;
  region?: string;
  language?: string;
  competitors?: Competitor[];
};
type ConfigurationVersion = {
  configuration_version_id: string;
  version_number: number;
  status: string;
  snapshot_hash: string;
  created_at: string;
  snapshot?: ConfigurationSnapshot;
};
type ConfigurationVersionList = { versions?: ConfigurationVersion[]; items?: ConfigurationVersion[] } | ConfigurationVersion[];

function versionsFrom(response: ConfigurationVersionList) {
  return Array.isArray(response) ? response : response.versions || response.items || [];
}

function snapshotFrom(version: ConfigurationVersion) {
  return version.snapshot || {};
}

export function ProjectConfigurationHistory({ projectId }: { projectId: number }) {
  const [versions, setVersions] = useState<ConfigurationVersion[]>();
  const [selectedVersionId, setSelectedVersionId] = useState<string>();
  const [selected, setSelected] = useState<ConfigurationVersion>();
  const [error, setError] = useState("");

  async function loadVersions() {
    setError(""); setVersions(undefined); setSelectedVersionId(undefined); setSelected(undefined);
    try {
      const response = await request<ConfigurationVersionList>(`/api/projects/${projectId}/configuration-versions`);
      setVersions(versionsFrom(response));
    } catch (e) { setError((e as Error).message); }
  }

  useEffect(() => { void loadVersions(); }, [projectId]);

  async function selectVersion(configurationVersionId: string) {
    setSelectedVersionId(configurationVersionId); setSelected(undefined); setError("");
    try {
      setSelected(await request<ConfigurationVersion>(
        projectConfigurationVersionPath(projectId, configurationVersionId),
      ));
    } catch (e) { setError((e as Error).message); }
  }

  const snapshot = selected && snapshotFrom(selected);
  return <section aria-label="项目配置历史" style={{ marginBottom: 16 }}>
    <Alert type="info" showIcon message="项目配置历史（只读）"
      description="历史版本是冻结快照，不能在此修改。仅标记为当前的版本可作为当前配置；SUPERSEDED 仅表示被替代的历史版本。" />
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message="读取配置历史失败" description={error} />}
    {!versions && !error && <Spin style={{ marginTop: 12 }} aria-label="正在读取配置历史" />}
    {versions && !versions.length && <Empty style={{ marginTop: 12 }} description="暂无配置历史版本" />}
    {!!versions?.length && <Space direction="vertical" size={12} style={{ width: "100%", marginTop: 12 }}>
      <Select aria-label="选择冻结配置版本" value={selectedVersionId} placeholder="选择一个冻结配置版本查看"
        onChange={value => void selectVersion(value)} options={versions.map(version => ({
          value: version.configuration_version_id,
          label: `V${version.version_number} · ${version.status} · ${version.snapshot_hash} · ${formatBeijingDateTime(version.created_at)}`,
        }))} />
      <Button onClick={() => void loadVersions()}>刷新配置历史</Button>
      {selectedVersionId !== undefined && !selected && !error && <Spin size="small" aria-label="正在读取冻结配置版本" />}
      {selected && <Descriptions size="small" column={1} bordered title={`冻结配置 V${selected.version_number}`}>
        <Descriptions.Item label="版本 / 状态">V{selected.version_number} <Tag color={selected.status === "EFFECTIVE" ? "green" : "default"}>{selected.status}</Tag></Descriptions.Item>
        <Descriptions.Item label="快照哈希"><code>{selected.snapshot_hash}</code></Descriptions.Item>
        <Descriptions.Item label="创建时间">{formatBeijingDateTime(selected.created_at)}</Descriptions.Item>
        <Descriptions.Item label="冻结品牌">{snapshot?.brand_name || "未提供"}</Descriptions.Item>
        <Descriptions.Item label="品牌别名">{snapshot?.brand_aliases?.join("、") || "未设置"}</Descriptions.Item>
        <Descriptions.Item label="品牌官网">{snapshot?.website_url || "未设置"}</Descriptions.Item>
        <Descriptions.Item label="地区 / 语言">{snapshot?.region || "未设置"} / {snapshot?.language || "未设置"}</Descriptions.Item>
        <Descriptions.Item label="竞品">{snapshot?.competitors?.length ? snapshot.competitors.map((competitor, index) =>
          <div key={`${competitor.name || "competitor"}:${index}`}>{competitor.name || "未命名"}；别名 {competitor.aliases?.join("、") || "未设置"}；官网 {competitor.website_url || "未设置"}</div>) : "未设置"}</Descriptions.Item>
      </Descriptions>}
    </Space>}
  </section>;
}
