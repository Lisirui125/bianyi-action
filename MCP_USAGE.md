# 便医行动 MCP 接入说明

## MCP 目标

便医行动 MCP 给上层 Agent 提供三个工具：

1. `get_intake_prompt`：新对话开场时提示用户需要输入哪些信息。
2. `search_nearest_hospitals`：根据用户真实定位或详细地址，在全国范围搜索附近医疗机构并计算距离。
3. `generate_care_plan`：生成完整就医任务单，包括双轴分级、医院推荐、地图/打车链接、医保政策卡和到院步骤。

重要原则：

- 最近医院不能由模型猜。
- 医院名称、地址、经纬度必须来自地图 API 或权威数据源。
- 模型只负责症状分流、解释原因、生成行动清单。
- 未配置商业地图 API 时，MCP 可使用 OSM/网页搜索/免费地理编码兜底，但必须标注距离和来源是否已验证。

## 启动

```bash
python -m pip install -r requirements.txt
```

地图提供者：

```bash
set MAP_PROVIDER=auto
```

`auto` 模式下：

- 有 `AMAP_API_KEY`：优先使用高德地图 Web 服务，适合中国大陆，数据更完整。
- 没有 `AMAP_API_KEY`：自动尝试 OpenStreetMap Overpass 免费公共数据源。
- OSM 无结果：自动尝试网页搜索兜底。若能用免费地理编码解析候选医院坐标，则计算直线距离；否则标记 `distance_verified=false`。

配置高德地图 Web 服务 Key，可选但推荐：

```bash
set AMAP_API_KEY=你的高德Web服务Key
```

启动 MCP：

```bash
python mcp_server.py
```

## 工具 1：search_nearest_hospitals

用途：给 Agent 做“全国范围最近医院搜索”。

注意：

- 推荐传 `lat/lng`，定位应由小程序、浏览器或客户端获取。
- 如果用户只提供详细地址，MCP 会先清洗“附近/周边”等口语后缀，再尝试用免费 Nominatim 地理编码转坐标。
- 候选医院有坐标时，MCP 会优先调用免费 OSRM 路线服务计算驾车路线距离；失败时退回直线距离。
- OSM 免费数据源在中国大陆医疗 POI 可能不完整，适合 MVP 验证，不适合生产级准确推荐。
- 网页搜索兜底如果补到坐标，会返回 `distance_km`；字段 `distance_type` 会说明是 `driving_route_by_osrm` 还是 `straight_line_by_free_geocode`。
- 免费地理编码和免费网页搜索无法稳定覆盖中国大陆所有小区、楼栋和医院。若 `origin` 或医院坐标为空，工具不会伪造距离。
- 高德/腾讯/百度地图更适合中国大陆正式产品。

### 输入

```json
{
  "symptoms": "头疼发热",
  "age": "25",
  "location": "河南省郑州市金水区正弘城附近",
  "radius": 5000,
  "danger_signals": [],
  "chronic_diseases": "",
  "income_context": "普通"
}
```

## 工具 0：get_intake_prompt

新对话开始时，Agent 可以先调用此工具，直接展示 `intake_prompt`，让用户知道需要填写：

- 必填：症状/病情描述、年龄、当前位置。
- 位置：尽量精确到小区、楼栋、学校、公司、商场或街道门牌。
- 选填：性别、持续时间、基础病、危险信号、医保类型、经济情况。

Agent 系统提示建议：

```text
新对话开始时，先调用 bianyi-action MCP 的 get_intake_prompt，
把 intake_prompt 展示给用户。用户提供症状、年龄和位置后，
调用 generate_care_plan，并原样输出 care_plan_text。
如果客户端能提供定位 lat/lng，一并传入；如果没有，只传用户详细地址。
```

### 输出

```json
{
  "classification": {
    "urgency": "non_urgent",
    "urgency_label": "非紧急：可预约门诊或专科评估",
    "severity": "mild",
    "severity_label": "轻症",
    "route_strategy": "nearest_primary",
    "route_strategy_label": "就近基层/普通门诊优先"
  },
  "departments": ["呼吸内科", "普通内科"],
  "search_status": "ok",
  "message": "已通过地图数据源返回候选机构。",
  "origin": {
    "lat": 34.78,
    "lng": 113.66
  },
  "places": [
    {
      "name": "附近社区卫生服务中心或医院",
      "address": "...",
      "lat": 34.78,
      "lng": 113.66,
      "distance_km": 1.2,
      "has_emergency": false,
      "source": "amap"
    }
  ]
}
```

### 规则

- 急症：搜索 `急诊`、`医院`，优先 `has_emergency=true` 和距离近。
- 小病：搜索 `社区卫生服务中心`、`社康中心`、`医院`，优先基层机构和距离近。
- 普通病：搜索推荐科室 + 医院，按距离排序。
- 癌症/肿瘤：搜索专科医院/肿瘤科；完整专科中心推荐由 `generate_care_plan` 给出。

## 工具 2：generate_care_plan

用途：生成完整患者任务单。

重要：如果用户需要“和网站一样的信息”，Agent 必须调用此工具，并把返回的
`care_plan_text` 或 `markdown` 原样展示。不要只调用 `search_nearest_hospitals`，
也不要自行摘要成几句话。

### 输入

```json
{
  "symptoms": "胸口压迫感，出汗，喘不上气",
  "age": "68",
  "location": "河南省郑州市金水区",
  "lat": 34.78,
  "lng": 113.66,
  "gender": "男",
  "duration": "1小时",
  "chronic_diseases": "高血压",
  "danger_signals": ["胸痛", "呼吸困难"],
  "insurance_type": "居民医保",
  "income_context": "普通"
}
```

### 输出

```json
{
  "care_plan_text": "# 便医行动任务单 ...",
  "markdown": "# 便医行动任务单 ...",
  "data": {
    "classification": {},
    "departments": [],
    "selected_place": {},
    "backup_places": [],
    "policy_cards": [],
    "map_url": "...",
    "navigation_url": "...",
    "taxi_url": "...",
    "map_search": {
      "status": "ok",
      "used": true
    }
  }
}
```

## 免费定位与免费地图方案

客户端定位通常免费：

- 微信小程序：`wx.getLocation`
- H5/浏览器：`navigator.geolocation.getCurrentPosition`

免费地图数据：

- OpenStreetMap Overpass：不需要 API Key，但中国大陆医疗机构数据不完整、稳定性和配额不适合高并发。
- Web 搜索兜底：不需要地图 Key，但不能证明真实最近距离，只能提供带来源链接的候选机构。

推荐 MVP 策略：

```text
用户输入详细地址；如果客户端可用，则同时获取 lat/lng
↓
MCP 先解析用户位置坐标
↓
MCP 用 OSM Overpass 免费查附近医院并计算直线距离
↓
如果无结果，使用网页搜索兜底
↓
网页结果能解析医院坐标则计算 OSRM 路线距离或直线距离，否则标记 distance_verified=false
↓
提示用户用地图 App 或医院官网二次确认
```

生产策略：

```text
小程序获取 lat/lng
↓
MCP 用高德/腾讯/百度地图查附近医院
↓
Agent 按病情策略筛选
```

## Agent 推荐调用流程

```text
用户输入症状、年龄、位置
↓
如果客户端有定位，传 lat/lng
↓
先调用 search_nearest_hospitals
↓
如果 search_status=ok，展示附近候选或继续调用 generate_care_plan
↓
调用 generate_care_plan 输出完整任务单
↓
Agent 原样展示 generate_care_plan.care_plan_text
↓
Agent 不得自行编造医院，不得把完整任务单压缩成摘要
```

## 合规声明

输出必须包含：

```text
本工具仅用于就医路径和医保信息辅助，不构成医学诊断、治疗建议、医院治疗效果承诺或医保报销承诺。真实医院地址、营业状态、号源、科室位置、收费和医保结算结果，请以医院、地图 App、医生和当地医保部门为准。
```
