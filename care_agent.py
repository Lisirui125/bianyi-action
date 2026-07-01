import json
import math
import re
from pathlib import Path
from urllib.parse import quote

from map_provider import search_nearby_hospitals


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


URGENCY_LABELS = {
    "immediate": "极紧急：建议立即拨打 120 或前往最近急诊",
    "emergency": "紧急：建议尽快前往有急诊能力的医院",
    "urgent": "较急：建议 24 小时内就医",
    "non_urgent": "非紧急：可预约门诊或专科评估",
}

SEVERITY_LABELS = {
    "mild": "轻症",
    "moderate": "普通/中等",
    "severe": "严重",
    "critical": "危重风险",
}

ROUTE_LABELS = {
    "nearest_emergency": "就近急救优先",
    "nearest_primary": "就近基层/普通门诊优先",
    "local_specialty": "本地专科优先",
    "national_specialty": "全国/区域专科中心优先",
}


DEPARTMENT_RULES = [
    (["癌", "肿瘤", "恶性", "化疗", "放疗", "病理"], ["肿瘤科", "肿瘤内科", "肿瘤外科"], "oncology"),
    (["胸痛", "胸口", "心梗", "心肌梗死", "心悸", "心慌", "出冷汗"], ["急诊科", "心血管内科"], "cardiology"),
    (["脑梗", "中风", "卒中", "口角歪斜", "说话不清", "肢体无力"], ["急诊科", "神经内科"], "neurology"),
    (["喘", "呼吸困难", "咳嗽", "咳痰", "发热", "发烧", "流鼻涕", "咽痛"], ["呼吸内科", "普通内科"], "respiratory"),
    (["腹痛", "肚子痛", "恶心", "呕吐", "腹泻", "黑便", "便血"], ["消化内科"], "gastroenterology"),
    (["皮疹", "过敏", "瘙痒", "红疹", "荨麻疹"], ["皮肤科"], "dermatology"),
    (["腰痛", "腿麻", "关节", "骨折", "扭伤", "走路"], ["骨科", "康复医学科"], "orthopedics"),
    (["伤口", "红肿", "感染", "糖尿病足"], ["内分泌科", "普外科", "伤口护理门诊"], "wound"),
    (["车祸", "动脉", "大出血", "割破", "外伤", "创伤"], ["急诊科", "创伤外科", "普外科"], "trauma"),
]


IMMEDIATE_KEYWORDS = [
    "心梗", "心肌梗死", "脑梗", "卒中", "中风", "口角歪斜", "说话不清", "单侧无力",
    "大量出血", "止不住血", "动脉", "车祸", "昏迷", "意识不清", "抽搐", "呼吸困难",
    "喘不上气", "胸痛", "胸口压迫",
]

EMERGENCY_KEYWORDS = [
    "高热", "39", "40", "剧烈疼痛", "呕血", "黑便", "咯血", "严重过敏", "喉头水肿",
    "骨折", "脱水", "精神差",
]

SEVERE_NON_URGENT_KEYWORDS = [
    "癌", "肿瘤", "恶性", "白血病", "淋巴瘤", "尿毒症", "器官移植", "罕见病",
]

MILD_KEYWORDS = [
    "头疼", "头痛", "头晕", "恶心", "流鼻涕", "咽痛", "轻微咳嗽", "低热", "发热",
]


def load_json(name):
    with (DATA_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_age(age_value):
    if age_value is None:
        return None
    match = re.search(r"\d+", str(age_value))
    return int(match.group()) if match else None


def contains_any(text, keywords):
    return any(keyword in text for keyword in keywords)


def has_negation_before(text, keyword, window=6):
    index = text.find(keyword)
    if index < 0:
        return False
    prefix = text[max(0, index - window):index]
    return any(word in prefix for word in ["无", "没有", "未出现", "未见", "否认", "不伴", "没"])


def contains_non_negated(text, keywords):
    for keyword in keywords:
        start = 0
        while True:
            index = text.find(keyword, start)
            if index < 0:
                break
            prefix = text[max(0, index - 6):index]
            if not any(word in prefix for word in ["无", "没有", "未出现", "未见", "否认", "不伴", "没"]):
                return True
            start = index + len(keyword)
    return False


def normalize_city(location):
    text = location or ""
    for city in ["杭州", "上海", "北京", "深圳", "广州", "成都"]:
        if city in text:
            return city
    return ""


def normalize_district(location):
    text = location or ""
    districts = [
        "东城区", "西城区", "朝阳区", "海淀区", "丰台区", "石景山区", "门头沟区", "房山区", "通州区",
        "顺义区", "昌平区", "大兴区", "怀柔区", "平谷区", "密云区", "延庆区", "浦东新区", "徐汇区",
        "西湖区", "上城区", "南山区", "福田区", "龙岗区", "天河区", "越秀区", "武侯区", "青羊区",
    ]
    for district in districts:
        if district in text:
            return district
    for short_name in ["大兴", "朝阳", "海淀", "丰台", "东城", "西城", "浦东", "徐汇", "西湖", "上城", "南山", "福田", "龙岗", "天河", "越秀", "武侯", "青羊"]:
        if short_name in text:
            return short_name + ("区" if not short_name.endswith("区") else "")
    return ""


def extract_duration_days(duration):
    if not duration:
        return None
    text = str(duration)
    number_match = re.search(r"\d+", text)
    number = int(number_match.group()) if number_match else 1
    if "月" in text:
        return number * 30
    if "周" in text or "星期" in text:
        return number * 7
    if "小时" in text:
        return max(1, math.ceil(number / 24))
    return number


def detect_danger_signals(symptoms, selected_signals):
    text = symptoms or ""
    signals = set(selected_signals or [])
    keyword_map = {
        "胸痛": ["胸痛", "胸口压迫", "胸闷", "心前区"],
        "呼吸困难": ["呼吸困难", "喘不上气", "气短", "憋气"],
        "意识异常": ["意识不清", "昏迷", "嗜睡", "叫不醒", "抽搐"],
        "大量出血": ["大量出血", "止不住血", "呕血", "咯血", "动脉"],
        "疑似中风": ["口角歪斜", "说话不清", "单侧无力", "半身麻木", "脑梗", "卒中"],
        "严重过敏": ["喉头水肿", "喉咙发紧", "喉咙紧", "全身过敏", "严重过敏", "喘憋"],
        "高热": ["高热", "39", "40", "发烧39", "发热39"],
        "剧烈疼痛": ["剧烈疼痛", "疼得受不了", "撕裂样疼痛"],
    }
    for signal, keywords in keyword_map.items():
        if contains_non_negated(text, keywords):
            signals.add(signal)
    return sorted(signals)


def recommend_departments(symptoms, age):
    text = symptoms or ""
    departments = []
    specialties = []
    for keywords, matched_departments, specialty in DEPARTMENT_RULES:
        if contains_non_negated(text, keywords):
            departments.extend(matched_departments)
            specialties.append(specialty)

    if age is not None and age < 14:
        if departments and "肿瘤科" not in departments:
            departments = ["儿科"] + [dept for dept in departments if dept != "普通内科"]
        elif not departments:
            departments = ["儿科"]
            specialties = ["pediatrics"]

    if not departments:
        departments = ["全科医学科", "普通内科"]
        specialties = ["general"]

    unique_departments = []
    for dept in departments:
        if dept not in unique_departments:
            unique_departments.append(dept)

    return unique_departments[:3], (specialties[0] if specialties else "general")


def classify_condition(symptoms, age, duration, chronic_diseases, danger_signals, income_context):
    text = f"{symptoms or ''} {chronic_diseases or ''}"
    reasons = []

    if danger_signals:
        reasons.append("用户主动选择或文本识别到危险信号：" + "、".join(danger_signals))
    if age is not None and age >= 65:
        reasons.append("老年患者风险上调")
    if age is not None and age < 6:
        reasons.append("儿童年龄较小，病情变化可能较快")
    if contains_any(chronic_diseases or "", ["糖尿病", "高血压", "冠心病", "心脏病", "肾病", "免疫"]):
        reasons.append("存在基础病，需要更谨慎分流")

    if contains_non_negated(text, IMMEDIATE_KEYWORDS) or any(
        signal in danger_signals for signal in ["胸痛", "呼吸困难", "意识异常", "大量出血", "疑似中风", "严重过敏"]
    ):
        urgency = "immediate"
        severity = "critical"
        route_strategy = "nearest_emergency"
        reasons.append("属于需要时间优先处理的急症线索，就近急救优先")
    elif contains_non_negated(text, EMERGENCY_KEYWORDS) or "高热" in danger_signals:
        urgency = "emergency"
        severity = "moderate"
        route_strategy = "nearest_emergency"
        reasons.append("存在急诊或较高风险线索，优先选择有急诊能力的就近医院")
    elif contains_non_negated(text, SEVERE_NON_URGENT_KEYWORDS):
        urgency = "non_urgent"
        severity = "severe"
        route_strategy = "national_specialty"
        reasons.append("疑似重大/疑难/长期治疗疾病线索，非急诊但严重，优先考虑高水平专科资源")
    elif contains_non_negated(text, MILD_KEYWORDS):
        urgency = "non_urgent"
        severity = "mild"
        route_strategy = "nearest_primary"
        reasons.append("症状更接近常见轻症，优先就近基层或普通门诊")
    else:
        duration_days = extract_duration_days(duration)
        urgency = "urgent" if duration_days and duration_days >= 7 else "non_urgent"
        severity = "moderate"
        route_strategy = "local_specialty"
        reasons.append("信息未提示明确急救危险信号，建议按门诊路径评估")

    if income_context and any(word in income_context for word in ["低", "困难", "贫困"]):
        reasons.append("经济困难场景：优先医保定点、本地可结算、可咨询救助的机构")

    return {
        "urgency": urgency,
        "urgency_label": URGENCY_LABELS[urgency],
        "severity": severity,
        "severity_label": SEVERITY_LABELS[severity],
        "route_strategy": route_strategy,
        "route_strategy_label": ROUTE_LABELS[route_strategy],
        "reason": "；".join(reasons),
    }


def hospital_matches_specialty(hospital, departments, specialty):
    fields = hospital.get("departments", []) + hospital.get("specialties", [])
    if any(dept in fields for dept in departments):
        return True
    specialty_keywords = {
        "oncology": ["肿瘤", "癌症", "国家癌症中心"],
        "cardiology": ["心血管", "胸痛中心"],
        "neurology": ["神经", "卒中中心"],
        "trauma": ["急诊", "创伤"],
        "orthopedics": ["骨科"],
        "respiratory": ["呼吸"],
    }
    return any(keyword in " ".join(fields) for keyword in specialty_keywords.get(specialty, []))


def match_hospitals(city, location, age, classification, departments, specialty, income_context):
    hospitals = load_json("hospitals.json")
    centers = load_json("national_centers.json")
    location_text = location or ""
    district = normalize_district(location)
    route_strategy = classification["route_strategy"]
    low_income = income_context and any(word in income_context for word in ["低", "困难", "贫困"])

    if route_strategy == "national_specialty":
        local = [item for item in hospitals if item["city"] == city and hospital_matches_specialty(item, departments, specialty)]
        national = [item for item in centers if specialty in item.get("specialty_codes", [])]
        candidates = local + national
    else:
        candidates = [item for item in hospitals if item["city"] == city]

    if route_strategy in ["nearest_emergency", "nearest_primary", "local_specialty"] and district:
        district_candidates = [item for item in candidates if item.get("district") == district]
        if route_strategy == "nearest_emergency":
            emergency_district_candidates = [item for item in district_candidates if item.get("has_emergency")]
            if emergency_district_candidates:
                candidates = emergency_district_candidates
            elif district_candidates:
                candidates = district_candidates
            else:
                return []
        elif district_candidates:
            candidates = district_candidates
        elif route_strategy in ["nearest_primary", "local_specialty"]:
            return []

    if not candidates:
        return []

    scored = []
    for hospital in candidates:
        score = 0
        if hospital.get("city") == city:
            score += 35
        if district and hospital.get("district") == district:
            score += 120 if route_strategy in ["nearest_emergency", "nearest_primary"] else 55
        elif hospital.get("district") and hospital["district"] in location_text:
            score += 60 if route_strategy in ["nearest_emergency", "nearest_primary"] else 20
        if hospital.get("insurance_designated"):
            score += 18 if low_income else 8
        if hospital_matches_specialty(hospital, departments, specialty):
            score += 18 if route_strategy in ["nearest_emergency", "nearest_primary"] else 30
        if route_strategy == "nearest_emergency":
            if hospital.get("has_emergency"):
                score += 45
            if hospital.get("level") == "三级甲等":
                score -= 8
        elif route_strategy == "nearest_primary":
            if hospital.get("type") == "community":
                score += 70
            if hospital.get("level") in ["基层医疗机构", "二级医院"]:
                score += 25
            if hospital.get("level") == "三级甲等":
                score -= 30
        elif route_strategy == "national_specialty":
            score += hospital.get("national_rank_score", 0)
            if low_income and hospital.get("city") != city:
                score -= 25
            if hospital.get("level") == "三级甲等":
                score += 10
        else:
            if hospital.get("level") in ["三级甲等", "三级医院", "二级医院"]:
                score += 18

        if age is not None and age < 14 and ("儿科" in hospital.get("departments", []) or hospital.get("type") == "children"):
            score += 30

        scored.append((score, hospital))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [hospital for _, hospital in scored[:3]]


def amap_marker_url(hospital):
    return (
        "https://uri.amap.com/marker"
        f"?position={hospital['lng']},{hospital['lat']}"
        f"&name={quote(hospital['name'])}"
        "&src=bianyi-agent&coordinate=gaode&callnative=1"
    )


def amap_nav_url(hospital):
    return (
        "https://uri.amap.com/navigation"
        f"?to={hospital['lng']},{hospital['lat']},{quote(hospital['name'])}"
        "&mode=car&policy=1&src=bianyi-agent&coordinate=gaode&callnative=1"
    )


def amap_taxi_url(hospital):
    return (
        "https://uri.amap.com/drive/takeTaxi"
        f"?dlat={hospital['lat']}&dlon={hospital['lng']}&dname={quote(hospital['name'])}"
        "&src=bianyi-agent&callnative=1"
    )


def build_arrival_steps(classification, hospital, departments, symptoms):
    primary_dept = departments[0]
    symptom_brief = symptoms.strip()[:100] if symptoms else "当前不适症状"

    if classification["route_strategy"] == "nearest_emergency":
        return [
            f"到达 {hospital['name']} 后，直接前往急诊入口，不要先去普通门诊。",
            "进入急诊大厅后，先找急诊预检分诊台或分诊护士。",
            f"向分诊护士说明：{symptom_brief}；同时说明年龄、基础病、开始时间和是否正在加重。",
            "出示身份证、医保卡或电子医保码，按分诊结果进入急诊诊区。",
            "按医嘱完成生命体征测量、心电图、检验、影像或急诊处置；需要缴费时去急诊收费窗口或自助机。",
            "拿到检查结果后回到急诊诊室复诊，不要自行离院。",
            "如医生安排留观、住院、手术或转院，先向急诊护士确认办理地点和下一步流程。",
            "如医生开具处方，完成缴费后到急诊药房取药，并向药师确认用法用量。",
        ]

    if classification["route_strategy"] == "nearest_primary" or hospital.get("type") == "community":
        return [
            f"到达 {hospital['name']} 后，从门诊入口进入。",
            "先到导诊台、自助机或挂号窗口，确认当天全科医学科/普通内科号源。",
            f"挂号建议：{primary_dept}；如现场导诊建议其他科室，以导诊结果为准。",
            "挂号后查看叫号屏或小票，前往对应候诊区。",
            f"见医生时说明：{symptom_brief}；补充持续时间、是否发热、是否用过药、是否有过敏史。",
            "如医生开检查，先到收费窗口或自助机结算，再去检验/检查区域。",
            "完成检查后回诊室复诊，让医生查看结果。",
            "如医生开具处方，完成医保结算后到门诊药房取药，并向药师确认用法用量和注意事项。",
        ]

    if classification["route_strategy"] == "national_specialty":
        return [
            f"先通过 {hospital['name']} 的官网、公众号或电话确认 {primary_dept} 号源和是否需要携带外院病理/影像资料。",
            "整理既往病历、病理报告、影像 DICOM 光盘或云影像、出院小结、用药清单。",
            "若本地已有诊断，优先在本地医保定点医院完成必要检查和转诊/异地备案咨询，减少跨城重复花费。",
            "到院后从门诊入口进入，先到导诊台确认专科门诊、特需门诊或多学科门诊的挂号方式。",
            f"挂号建议：{primary_dept}；如属于疑难复杂病情，可询问是否适合 MDT 多学科门诊。",
            "候诊时准备一页纸病情摘要：首次发现时间、检查结果、治疗经过、当前最需要解决的问题。",
            "医生开检查后，按医院指引缴费、检查、取报告，并确认是否需要本院复诊或远程复诊。",
            "离院前确认下一步治疗路径、复诊时间、是否需要住院排队、医保/异地结算材料。",
        ]

    return [
        f"到达 {hospital['name']} 后，从门诊入口进入。",
        "先到门诊大厅导诊台、自助机或挂号窗口。",
        f"挂号建议：{primary_dept}；若导诊台判断更适合其他科室，以现场导诊为准。",
        "挂号后查看叫号屏、挂号小票或医院公众号提示，前往对应候诊区；本工具不编造具体楼层和诊室号。",
        f"见医生时说明：{symptom_brief}；补充持续时间、诱因、加重缓解因素、基础病和既往检查结果。",
        "如果医生开检查，先到收费窗口/自助机/手机端完成缴费或医保结算，再去检验、影像或功能检查区。",
        "检查完成后按取报告提示返回诊室复诊，确认是否需要复查、转科或住院。",
        "如医生开具处方，完成缴费后到门诊药房取药，并向药师确认用法用量、禁忌和复诊时间。",
    ]


def build_preparation(age, chronic_diseases, income_context, classification):
    items = [
        "身份证",
        "医保卡或电子医保码",
        "手机和充电宝",
        "既往病历、检查报告、影像片或电子报告",
        "正在使用的药品名称、剂量和最近一次服药时间",
        "过敏史记录",
    ]
    if age is not None and age < 14:
        items.extend(["儿童预防接种本或既往儿科病历", "监护人身份证件"])
    if chronic_diseases:
        items.append("慢病诊断材料、近期复诊记录或血压/血糖记录")
    if classification["route_strategy"] == "national_specialty":
        items.extend(["病理报告、免疫组化/基因检测报告，如有", "影像 DICOM 光盘或云影像链接", "本地医生转诊建议或出院小结，如有"])
    if income_context and any(word in income_context for word in ["低", "困难", "贫困"]):
        items.append("如已有困难证明、低保证明或救助材料，可一并携带以便咨询")
    return items


def select_policy_card(city, insurance_type, classification, chronic_diseases, income_context):
    cards = load_json("policy_cards.json")
    city_cards = cards.get(city) or cards.get("default", [])
    selected = []

    if classification["route_strategy"] == "nearest_emergency":
        scenario = "emergency"
    elif classification["severity"] in ["severe", "critical"]:
        scenario = "serious_disease"
    else:
        scenario = "outpatient"

    for card in city_cards:
        if card.get("scenario") in [scenario, "general"]:
            if card.get("insurance_type") in [insurance_type, "通用", "不清楚"]:
                selected.append(card)

    if chronic_diseases:
        selected.extend([card for card in city_cards if card.get("scenario") == "chronic"])
    if income_context and any(word in income_context for word in ["低", "困难", "贫困"]):
        selected.extend([card for card in city_cards if card.get("scenario") == "medical_aid"])
    if insurance_type and ("外地" in insurance_type or "异地" in insurance_type):
        selected.extend([card for card in city_cards if card.get("scenario") == "remote"])

    if not selected and scenario == "emergency":
        for card in city_cards:
            if card.get("scenario") in ["outpatient", "general"]:
                if card.get("insurance_type") in [insurance_type, "通用", "不清楚"]:
                    selected.append(card)

    if not selected:
        selected = cards["default"]

    unique = []
    seen = set()
    for card in selected:
        key = (card.get("title"), card.get("source_url"))
        if key not in seen:
            unique.append(card)
            seen.add(key)
    return unique[:4]


def policy_cards_to_markdown(cards):
    lines = []
    for card in cards:
        lines.append(f"### {card['title']}")
        lines.append(f"- 适用场景：{card['scenario_label']}")
        lines.append(f"- 政策要点：{card['summary']}")
        if card.get("reimbursement_hint"):
            lines.append(f"- 报销/救助提示：{card['reimbursement_hint']}")
        lines.append(f"- 核验状态：{card['verification_status']}")
        if card.get("source_url"):
            lines.append(f"- 来源：[{card['source_name']}]({card['source_url']})")
        lines.append("")
    lines.append("- 注意：医保政策会调整，最终结算以医院医保系统、当地医保部门和参保状态为准。")
    return "\n".join(lines)


def immediate_escalation_text():
    return [
        "胸痛、胸闷伴出汗、气短或放射痛",
        "呼吸困难、嘴唇发紫、血氧异常",
        "意识不清、抽搐、叫不醒",
        "疑似中风：口角歪斜、说话不清、单侧肢体无力",
        "大量出血、呕血、咯血、黑便，或割破动脉/车祸外伤",
        "儿童或老人高热伴精神差、持续呕吐或脱水表现",
        "严重过敏伴喉咙发紧、喘憋或全身皮疹快速加重",
    ]


def generate_plan(
    symptoms,
    age,
    location,
    gender="未填写",
    duration="",
    chronic_diseases="",
    danger_signals=None,
    insurance_type="不清楚",
    income_context="",
    lat=None,
    lng=None,
):
    parsed_age = parse_age(age)
    city = normalize_city(location)
    detected_signals = detect_danger_signals(symptoms, danger_signals)
    departments, specialty = recommend_departments(symptoms, parsed_age)
    classification = classify_condition(symptoms, parsed_age, duration, chronic_diseases, detected_signals, income_context)
    map_result = search_nearby_hospitals(location, classification, departments, lat=lat, lng=lng)
    if map_result["places"]:
        hospitals = map_result["places"]
    else:
        hospitals = match_hospitals(city, location, parsed_age, classification, departments, specialty, income_context)
    selected = hospitals[0] if hospitals else None

    if selected:
        steps = build_arrival_steps(classification, selected, departments, symptoms or "")
        if selected.get("lat") is not None and selected.get("lng") is not None:
            map_url = amap_marker_url(selected)
            nav_url = amap_nav_url(selected)
            taxi_url = amap_taxi_url(selected)
        else:
            map_url = selected.get("source_url", "")
            nav_url = ""
            taxi_url = ""
    else:
        steps = [
            "当前内置 MVP 数据未覆盖该区县的可确认医院/基层机构，不能为了凑结果默认推荐市中心三甲医院。",
            "正式接入小程序时，应调用高德/腾讯地图地点搜索 API，用用户经纬度查询最近的急诊、社区卫生服务中心或推荐科室。",
            "如果存在危险信号，请优先拨打 120 或前往最近急诊。",
        ]
        map_url = nav_url = taxi_url = ""

    prep_items = build_preparation(parsed_age, chronic_diseases, income_context, classification)
    policy_cards = select_policy_card(city, insurance_type, classification, chronic_diseases, income_context)

    backup_md = "\n".join(
        f"- {hospital['name']}：{hospital['address']}，{hospital['level']}，{'有急诊' if hospital.get('has_emergency') else '非急诊优先'}"
        for hospital in hospitals[1:]
    ) or "- 暂无备用医院数据。"

    if selected:
        map_lines = ""
        if selected.get("lat") is not None and selected.get("lng") is not None:
            distance_line = ""
            if selected.get("distance_km") is not None:
                distance_line = f"\n\n**距离**：约 {selected['distance_km']} 公里（{selected.get('distance_note') or '直线距离，实际路线以地图 App 为准'}）"
            map_lines = f"""**地图定位**：[打开地点]({map_url})

**驾车导航**：[打开导航]({nav_url})

**打车入口**：[呼叫打车]({taxi_url}){distance_line}"""
        elif selected.get("source_url"):
            map_lines = f"""**网页来源**：[查看来源]({selected.get('source_url')})

**距离状态**：网页搜索结果未验证真实距离，不能证明这是最近医院。建议在地图 App 中再次搜索确认。"""
        else:
            map_lines = "**地图状态**：当前结果没有可用经纬度，不能生成导航和打车链接。"

        source_note = ""
        if selected.get("source") == "web_search":
            if selected.get("distance_verified"):
                source_note = "\n\n**来源提醒**：该地点来自网页搜索兜底，距离由免费地理编码换算为直线距离；名称、地址、营业状态、急诊能力和行车时间需以医院官网或地图 App 再次核验。"
            else:
                source_note = "\n\n**来源提醒**：该地点来自网页搜索兜底，名称和地址需以医院官网或地图 App 再次核验。"

        place_md = f"""**推荐地点**：{selected['name']}

**地址**：{selected['address']}

**等级/类型**：{selected['level']} / {selected['type']}

**推荐入口**：{selected['recommended_entrance']}

{map_lines}

**联系电话**：{selected['phone_note']}

**为什么推荐**：当前策略为“{classification['route_strategy_label']}”。{classification['reason']}{source_note}"""
    else:
        place_md = "**暂无可确认地点**：内置 MVP 数据未覆盖该区县，系统不会默认推荐远处名院。请接入地图/医院 API 后按真实距离返回最近机构。"

    md = f"""# 便医行动任务单

## 病情双轴分级

**紧急程度**：{classification['urgency_label']}

**严重程度**：{classification['severity_label']}

**推荐路径策略**：{classification['route_strategy_label']}

**判断依据**：{classification['reason']}

**建议科室**：{'、'.join(departments)}

## 现在要去哪里

{place_md}

## 备用选择

{backup_md}

## 到院后怎么走

{chr(10).join(f"{idx}. {step}" for idx, step in enumerate(steps, 1))}

## 出发前准备

{chr(10).join(f"- {item}" for item in prep_items)}

## 见医生时这样说

- 主要症状：{symptoms or '未填写'}
- 年龄/性别：{age or '未填写'} / {gender or '未填写'}
- 持续时间：{duration or '未填写'}
- 基础病：{chronic_diseases or '未填写'}
- 已出现的危险信号：{'、'.join(detected_signals) if detected_signals else '未发现或未填写'}
- 希望医生帮助确认：是否需要急诊处理、是否需要转科、是否需要住院、是否需要专科中心进一步评估

## 当地医保/报销政策卡

{policy_cards_to_markdown(policy_cards)}

## 需要立即升级为急诊的情况

{chr(10).join(f"- {item}" for item in immediate_escalation_text())}

## 工具局限性声明

本工具仅用于就医路径和医保信息辅助，不构成医学诊断、治疗建议、医院治疗效果承诺或医保报销承诺。真实医院地址、营业状态、号源、科室位置、楼层、收费和医保结算结果，请以医院、地图 App、医生和当地医保部门为准。
"""

    payload = {
        "classification": classification,
        "risk": {
            "level": classification["urgency"],
            "label": classification["urgency_label"],
            "reason": classification["reason"],
        },
        "departments": departments,
        "specialty": specialty,
        "selected_place": selected,
        "backup_places": hospitals[1:],
        "policy_cards": policy_cards,
        "detected_danger_signals": detected_signals,
        "map_url": map_url,
        "navigation_url": nav_url,
        "taxi_url": taxi_url,
        "map_search": {
            "status": map_result.get("status"),
            "message": map_result.get("message"),
            "origin": map_result.get("origin"),
            "used": bool(map_result.get("places")),
        },
    }
    return md, payload


if __name__ == "__main__":
    demo, data = generate_plan(
        symptoms="疑似肺癌，已经做了CT，想找更好的医院进一步确认",
        age="56",
        location="深圳南山区",
        gender="男",
        duration="1个月",
        chronic_diseases="无",
        danger_signals=[],
        insurance_type="外地居民医保",
        income_context="普通",
    )
    print(demo)
