import { useState } from "react";
import { Alert, Button, Descriptions, Empty, Modal, Select, Space, Spin, Tag } from "antd";
import { request } from "./api/client";

type PromptSnapshot = {
  prompt_text?: string;
  title?: string;
  intent_type?: string;
  prompt_group?: string;
  enabled?: boolean;
};
type PromptVersion = {
  prompt_version_id: string;
  version_number: number;
  status: string;
  snapshot_hash: string;
  created_at: string;
  snapshot?: PromptSnapshot;
};

export function PromptVersionHistory({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<PromptVersion[]>();
  const [selectedVersionId, setSelectedVersionId] = useState<string>();
  const [selected, setSelected] = useState<PromptVersion>();
  const [error, setError] = useState("");

  async function loadVersions() {
    setError(""); setVersions(undefined); setSelectedVersionId(undefined); setSelected(undefined);
    try {
      setVersions(await request<PromptVersion[]>(`/api/projects/${projectId}/prompts/${promptId}/versions`));
    } catch (e) { setError((e as Error).message); }
  }

  async function selectVersion(promptVersionId: string) {
    setError(""); setSelectedVersionId(promptVersionId); setSelected(undefined);
    try {
      setSelected(await request<PromptVersion>(
        `/api/projects/${projectId}/prompts/${promptId}/versions/${encodeURIComponent(promptVersionId)}`,
      ));
    } catch (e) { setError((e as Error).message); }
  }

  function showHistory() {
    setOpen(true);
    void loadVersions();
  }

  const snapshot = selected?.snapshot;
  return <>
    <Button size="small" onClick={showHistory}>查看版本历史</Button>
    <Modal open={open} title="Prompt 版本历史（只读）" footer={null} onCancel={() => setOpen(false)} destroyOnHidden>
      <Alert type="info" showIcon message="历史版本为冻结快照，只读不可修改。"
        description="SUPERSEDED 表示已被替代的历史版本，不是当前 Prompt；此处不提供历史修改操作。" />
      {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message="读取 Prompt 版本失败" description={error} />}
      {!versions && !error && <Spin style={{ marginTop: 12 }} aria-label="正在读取 Prompt 版本历史" />}
      {versions && !versions.length && <Empty style={{ marginTop: 12 }} description="暂无 Prompt 历史版本" />}
      {!!versions?.length && <Space direction="vertical" size={12} style={{ width: "100%", marginTop: 12 }}>
        <Select aria-label="选择冻结 Prompt 版本" value={selectedVersionId} placeholder="选择一个冻结版本查看"
          onChange={value => void selectVersion(value)} options={versions.map(version => ({
            value: version.prompt_version_id,
            label: `V${version.version_number} · ${version.status} · ${version.snapshot_hash} · ${version.created_at}`,
          }))} />
        {selectedVersionId !== undefined && !selected && !error && <Spin size="small" aria-label="正在读取冻结 Prompt 版本" />}
        {selected && <Descriptions size="small" column={1} bordered title={`冻结 Prompt V${selected.version_number}`}>
          <Descriptions.Item label="版本 / 状态">V{selected.version_number} <Tag color={selected.status === "EFFECTIVE" ? "green" : "default"}>{selected.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="快照哈希"><code>{selected.snapshot_hash}</code></Descriptions.Item>
          <Descriptions.Item label="创建时间">{selected.created_at}</Descriptions.Item>
          <Descriptions.Item label="冻结问题内容">{snapshot?.prompt_text || "未提供"}</Descriptions.Item>
          <Descriptions.Item label="标题">{snapshot?.title || "未提供"}</Descriptions.Item>
          <Descriptions.Item label="意图类型">{snapshot?.intent_type || "未提供"}</Descriptions.Item>
          <Descriptions.Item label="问题组">{snapshot?.prompt_group || "未提供"}</Descriptions.Item>
          <Descriptions.Item label="启用状态">{snapshot?.enabled === true ? "已启用" : snapshot?.enabled === false ? "已停用" : "未提供"}</Descriptions.Item>
        </Descriptions>}
      </Space>}
    </Modal>
  </>;
}
