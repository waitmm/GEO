import { useEffect, useState } from "react";
import { Alert, Button, Select, Space, Tooltip } from "antd";
import { RefreshCw } from "lucide-react";
import { request } from "./api/client";

type ContextVersion = { project_id: number; context_version_id: string; version_number: number; title: string };

export function BrandContextSelect({ projectId, value, onChange }: { projectId: number; value?: string; onChange: (value?: string) => void }) {
  const [loaded, setLoaded] = useState<{ projectId: number; items: ContextVersion[] }>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true); setError(""); setLoaded(undefined);
    request<ContextVersion[]>(`/api/v2/projects/${projectId}/brand-contexts`, { signal: c.signal })
      .then(items => { if (!c.signal.aborted) setLoaded({ projectId, items: items.filter(item => item.project_id === projectId) }); })
      .catch(e => { if (!c.signal.aborted) setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [projectId, revision]);
  const items = loaded?.projectId === projectId ? loaded.items : [];
  return <Space direction="vertical" style={{ width: "100%" }}>
    {error && <Alert type="error" message="品牌资料读取失败" description={error} />}
    <Space.Compact style={{ width: "100%" }}>
      <Select aria-label="补充品牌资料版本" allowClear value={value} onChange={onChange} loading={loading}
        disabled={loading || !!error} style={{ flex: 1, minWidth: 0 }} placeholder="不使用补充资料"
        notFoundContent="暂无品牌资料版本" options={items.map(x => ({ value: x.context_version_id, label: `资料版本 ${x.version_number} · ${x.title}` }))} />
      <Tooltip title={error ? "重试读取品牌资料" : "刷新品牌资料版本"}>
        <Button aria-label="刷新品牌资料版本" icon={<RefreshCw size={16} />} disabled={loading} onClick={() => setRevision(n => n + 1)} />
      </Tooltip>
    </Space.Compact>
  </Space>;
}
