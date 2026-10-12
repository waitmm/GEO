import { Checkbox, Col, Input, Row, Typography } from 'antd';

type Props = { selection: Record<string, any>; onChange: (check: Record<string, any>) => void };

export function AssetVerificationFields({ selection, onChange }: Props) {
  if (!['CREATE_NEW', 'UPDATE_EXISTING'].includes(selection.asset_operation)) return null;
  const check = selection.asset_verification || {};
  const update = (patch: Record<string, any>) => onChange({ ...check,
    asset_type: selection.asset_type || '', publication_surface: selection.publication_surface || '', ...patch });
  const field = (key: string, label: string, limit: number) => <Col xs={24} md={12} key={key}>
    <label>{label}<Input value={check[key] || ''} maxLength={limit} onChange={e => update({ [key]: e.target.value,
      inventory_complete: false, no_suitable_existing: false, editable: false, content_fit: false })} /></label>
  </Col>;
  return <section aria-label="资产核查信息">
    <Typography.Paragraph type="secondary">核查记录：用户提供，系统未验证页面权限。只影响发布位置确认，正文与原始证据不变。</Typography.Paragraph>
    <Row gutter={[12, 12]}>
      {field('inventory_scope', '已核查的栏目或页面范围', 1000)}
      {selection.asset_operation === 'CREATE_NEW' ? <Col span={24}>
        <Checkbox checked={check.inventory_complete === true && check.no_suitable_existing === true}
          onChange={e => update({ inventory_complete: e.target.checked, no_suitable_existing: e.target.checked,
            url: '', title: '', content_version: '', ownership_basis: '', editable: false, content_fit: false })}>
          已完成上述范围核查，确认没有适合更新的现有资产
        </Checkbox>
      </Col> : <>
        {field('url', '已有页面 URL', 2000)}
        {field('title', '已有页面标题', 300)}
        {field('content_version', '页面当前版本或最后修改时间', 300)}
        {field('ownership_basis', '品牌归属及编辑权限依据', 1000)}
        <Col span={24}><Checkbox checked={check.editable === true} onChange={e => update({ editable: e.target.checked, no_suitable_existing: false })}>确认具有该页面的编辑权限</Checkbox></Col>
        <Col span={24}><Checkbox checked={check.content_fit === true} onChange={e => update({ content_fit: e.target.checked, no_suitable_existing: false })}>确认该页面适合承接当前稿件</Checkbox></Col>
      </>}
    </Row>
  </section>;
}
