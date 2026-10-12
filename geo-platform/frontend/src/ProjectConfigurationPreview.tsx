import { useEffect, useState } from 'react';
import { Alert, Descriptions, Form, Spin } from 'antd';
import { request } from './api/client';
import { projectConfigurationPayload } from './projectConfiguration';

type Preview = {
  values: { name: string; brand_name: string; brand_aliases: string[]; region: string; language: string };
  configured_official_host: string | null; alias_duplicates_removed: number;
};

export function ProjectConfigurationPreview({ projectId }: { projectId: number | null }) {
  const form = Form.useFormInstance();
  const values = Form.useWatch([], form) || {};
  const payload = JSON.stringify(projectConfigurationPayload(values));
  const ready = !!values.name?.trim() && !!values.brand_name?.trim();
  const [result, setResult] = useState<{ input: string; preview?: Preview; error?: string }>();
  useEffect(() => {
    if (!ready) return;
    const c = new AbortController();
    const timer = window.setTimeout(() => {
      const query = projectId ? `?project_id=${projectId}` : '';
      void request<Preview>(`/api/projects/configuration-preview${query}`, { method: 'POST', body: payload, signal: c.signal })
        .then(preview => { if (!c.signal.aborted) setResult({ input: payload, preview }); })
        .catch(e => { if (!c.signal.aborted) setResult({ input: payload, error: e.message }); });
    }, 300);
    return () => { window.clearTimeout(timer); c.abort(); };
  }, [payload, projectId, ready]);
  if (!ready) return null;
  const current = result?.input === payload ? result : undefined;
  const preview = current?.preview;
  return <section aria-label="保存配置预览" style={{ marginBottom: 16 }}>
    {!current && <Spin size="small" aria-label="正在核对配置" />}
    {current?.error && <Alert type="error" showIcon message="配置尚未通过校验" description={current.error} />}
    {preview && <Descriptions title="保存配置预览" size="small" column={1}>
      <Descriptions.Item label="项目 / 品牌">{preview.values.name} / {preview.values.brand_name}</Descriptions.Item>
      <Descriptions.Item label="归一化别名">{preview.values.brand_aliases.join('、') || '未设置'}{preview.alias_duplicates_removed > 0 ? `（已合并 ${preview.alias_duplicates_removed} 项重复）` : ''}</Descriptions.Item>
      <Descriptions.Item label="配置域名">{preview.configured_official_host || '未配置，官方来源归属未知'}{preview.configured_official_host ? '（用户配置，未核实所有权）' : ''}</Descriptions.Item>
      <Descriptions.Item label="地区 / 语言">{preview.values.region} / {preview.values.language}</Descriptions.Item>
    </Descriptions>}
  </section>;
}
