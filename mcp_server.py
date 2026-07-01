from typing import List

from mcp.server.fastmcp import FastMCP

from care_agent import classify_condition, detect_danger_signals, generate_plan, parse_age, recommend_departments
from map_provider import search_nearby_hospitals


mcp = FastMCP("bianyi-action-mcp")


@mcp.tool()
def get_intake_prompt() -> dict:
    """返回新对话时给患者展示的信息采集提示。"""
    text = """为了生成具体就医路径，请先提供以下信息：

必填：
1. 症状/病情描述：哪里不舒服、主要表现是什么。
2. 年龄。
3. 当前位置：尽量精确到小区、楼栋、学校、公司、商场或街道门牌。

建议补充：
1. 性别。
2. 持续时间：例如 1小时、2天、1个月。
3. 基础病：高血压、糖尿病、肿瘤病史、孕期等；没有可填“无”。
4. 危险信号：胸痛、呼吸困难、意识异常、大量出血、疑似中风、严重过敏、高热、剧烈疼痛等。
5. 医保类型：职工医保、居民医保、新农合、外地医保、不清楚或自费。
6. 经济情况：普通、收入较低、经济困难。

示例：
“我 68 岁，男，在河南省郑州市金水区正弘城附近，胸口压迫感 1 小时，出汗，喘不上气，有高血压，职工医保。”"""
    return {
        "intake_prompt": text,
        "required_fields": ["symptoms", "age", "location"],
        "optional_fields": [
            "gender",
            "duration",
            "chronic_diseases",
            "danger_signals",
            "insurance_type",
            "income_context",
            "lat",
            "lng",
        ],
        "disclaimer": "本工具仅用于就医路径和医保信息辅助，不构成医学诊断、治疗建议、医院治疗效果承诺或医保报销承诺。",
    }


@mcp.tool()
def search_nearest_hospitals(
    symptoms: str,
    age: str,
    location: str,
    lat: float | None = None,
    lng: float | None = None,
    radius: int = 5000,
    danger_signals: List[str] | None = None,
    chronic_diseases: str = "",
    income_context: str = "",
) -> dict:
    """全国范围按真实定位或详细地址搜索最近医疗机构。

    推荐传入小程序或客户端定位 `lat/lng`。如果没有经纬度，工具会尝试用
    免费地理编码把详细地址解析为坐标，再搜索医疗机构并计算直线距离。
    不允许模型凭空生成医院名称。根据病情策略搜索急诊、社区卫生服务中心、
    普通医院或专科医院。
    """
    parsed_age = parse_age(age)
    signals = detect_danger_signals(symptoms, danger_signals or [])
    departments, specialty = recommend_departments(symptoms, parsed_age)
    classification = classify_condition(symptoms, parsed_age, "", chronic_diseases, signals, income_context)
    result = search_nearby_hospitals(
        location_text=location,
        classification=classification,
        departments=departments,
        lat=lat,
        lng=lng,
        radius=radius,
    )
    return {
        "classification": classification,
        "departments": departments,
        "search_status": result.get("status"),
        "message": result.get("message"),
        "origin": result.get("origin"),
        "places": result.get("places", []),
        "disclaimer": "最近医院必须以地图 API、实时路况和医院实际接诊能力为准；本工具不做诊断。",
    }


@mcp.tool()
def generate_care_plan(
    symptoms: str,
    age: str,
    location: str,
    gender: str = "未填写",
    duration: str = "",
    chronic_diseases: str = "",
    danger_signals: List[str] | None = None,
    insurance_type: str = "不清楚",
    income_context: str = "",
    lat: float | None = None,
    lng: float | None = None,
    radius: int = 5000,
) -> dict:
    """生成便医行动就医任务单。

    不做诊断，不开药，不承诺治疗效果。输出双轴病情分级、医院匹配、
    地图/打车链接、到院行动清单和当地医保政策卡。
    """
    markdown, data = generate_plan(
        symptoms=symptoms,
        age=age,
        location=location,
        gender=gender,
        duration=duration,
        chronic_diseases=chronic_diseases,
        danger_signals=danger_signals or [],
        insurance_type=insurance_type,
        income_context=income_context,
        lat=lat,
        lng=lng,
    )
    return {
        "care_plan_text": markdown,
        "markdown": markdown,
        "data": data,
        "disclaimer": "本工具仅用于就医路径和医保信息辅助，不构成医学诊断、治疗建议、医院治疗效果承诺或医保报销承诺。",
    }


if __name__ == "__main__":
    mcp.run()
