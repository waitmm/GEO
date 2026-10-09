import { useEffect, useState } from "react";
import { Alert, Select, Space } from "antd";
import { request } from "./api/client";

export function BrandContextSelect({ projectId, value, onChange }: { projectId: number; value?: string; onChange: (value?: string) => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    request<any[]>(`/api/v2/projects/${projectId}/brand-contexts`, { signal: c.signal }).then(setItems).catch(e => { if (!c.signal.aborted) setError(e.message); });
    return () => c.abort();
  }, [projectId]);
  return <Space direction="vertical" style={{ width: "100%" }}>
    {error && <Alert type="error" message={error} />}
    <Select aria-label="补充品牌资料版本" allowClear value={value} onChange={onChange} style={{ width: "100%" }} placeholder="不使用补充资料" options={items.map(x => ({ value: x.context_version_id, label: `资料版本 ${x.version_number} · ${x.title}` }))} />
  </Space>;
}
