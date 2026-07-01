from care_agent import classify_condition, detect_danger_signals, parse_age, recommend_departments


CASES = [
    {
        "name": "普通感冒样症状",
        "symptoms": "流鼻涕、轻微咳嗽2天，没有胸痛，没有呼吸困难",
        "age": "25",
        "duration": "2天",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("non_urgent", "mild", "nearest_primary"),
    },
    {
        "name": "皮疹瘙痒无呼吸困难",
        "symptoms": "手臂皮疹瘙痒半天，没有发热，没有呼吸困难",
        "age": "20",
        "duration": "半天",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("non_urgent", "moderate", "local_specialty"),
    },
    {
        "name": "儿童高热精神差",
        "symptoms": "发烧39.5度，精神不太好，偶尔咳嗽",
        "age": "4",
        "duration": "1天",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("emergency", "moderate", "nearest_emergency"),
    },
    {
        "name": "糖尿病伤口一周红肿",
        "symptoms": "脚上有个小伤口，一周没好，有点红肿",
        "age": "59",
        "duration": "7天",
        "chronic_diseases": "糖尿病10年",
        "danger_signals": [],
        "income_context": "收入较低",
        "expected": ("urgent", "moderate", "local_specialty"),
    },
    {
        "name": "慢性腰痛腿麻",
        "symptoms": "腰痛、腿麻，走路久了加重，持续一个月",
        "age": "52",
        "duration": "1个月",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("urgent", "moderate", "local_specialty"),
    },
    {
        "name": "疑似肺癌已做CT",
        "symptoms": "疑似肺癌，已经做了CT，想找更好的医院进一步确认",
        "age": "56",
        "duration": "1个月",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("non_urgent", "severe", "national_specialty"),
    },
    {
        "name": "胸口压迫出汗喘不上气",
        "symptoms": "胸口压迫感1小时，出汗，喘不上气",
        "age": "68",
        "duration": "1小时",
        "chronic_diseases": "高血压",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("immediate", "critical", "nearest_emergency"),
    },
    {
        "name": "疑似中风",
        "symptoms": "突然口角歪斜，说话不清，右侧肢体无力",
        "age": "72",
        "duration": "30分钟",
        "chronic_diseases": "高血压",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("immediate", "critical", "nearest_emergency"),
    },
    {
        "name": "车祸大量出血",
        "symptoms": "车祸外伤，大量出血，按压后仍止不住血",
        "age": "35",
        "duration": "刚刚",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("immediate", "critical", "nearest_emergency"),
    },
    {
        "name": "严重过敏喉咙发紧",
        "symptoms": "吃海鲜后全身皮疹，喉咙发紧，喘憋",
        "age": "30",
        "duration": "20分钟",
        "chronic_diseases": "无",
        "danger_signals": [],
        "income_context": "普通",
        "expected": ("immediate", "critical", "nearest_emergency"),
    },
]


def main():
    passed = 0
    for case in CASES:
        age = parse_age(case["age"])
        signals = detect_danger_signals(case["symptoms"], case["danger_signals"])
        departments, _ = recommend_departments(case["symptoms"], age)
        classification = classify_condition(
            case["symptoms"],
            age,
            case["duration"],
            case["chronic_diseases"],
            signals,
            case["income_context"],
        )
        actual = (
            classification["urgency"],
            classification["severity"],
            classification["route_strategy"],
        )
        ok = actual == case["expected"]
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} | {case['name']}")
        print(f"  expected: {case['expected']}")
        print(f"  actual:   {actual}")
        print(f"  signals:  {signals}")
        print(f"  dept:     {'、'.join(departments)}")
        print(f"  reason:   {classification['reason']}")
        print()

    print(f"summary: {passed}/{len(CASES)} passed")


if __name__ == "__main__":
    main()
