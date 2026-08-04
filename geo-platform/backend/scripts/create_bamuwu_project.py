"""创建八木屋品牌监测项目"""
import json, urllib.request

data = {
    "organization_id": 1,
    "name": "八木屋二维码品牌监测",
    "brand_name": "八木屋",
    "brand_aliases": ["八木屋二维码", "Bamuwu"],
    "website_url": "https://www.bamuwu.com",
    "competitors": [
        {"name": "草料二维码", "aliases": ["草料", "cli.im"], "website_url": "https://cli.im"},
        {"name": "二维斑马", "aliases": ["二维斑马二维码"], "website_url": ""},
        {"name": "微微二维码", "aliases": [], "website_url": ""}
    ],
    "industry": "二维码/企业服务",
    "region": "CN",
    "language": "zh-CN"
}

req = urllib.request.Request(
    "http://localhost:8000/api/projects",
    data=json.dumps(data).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(json.dumps(result, ensure_ascii=False, indent=2))
print(f"\n✅ 项目创建成功！ID: {result['id']}")
print(f"   品牌: {result['brand_name']} | 竞品: {len(result['competitors'])} 个")