from datetime import timedelta

# 같은 주기인데도 API가 돌려주는 초기화 시각이 몇 초씩 흔들릴 수 있다.
RESET_SLACK = timedelta(minutes=1)


def check(reports, sent, threshold):
    """reports 의 각 한도를 보고 보낼 알림 목록을 돌려주고 sent 를 갱신한다.
    sent 는 {(provider, account id, window label): {"reset_at": datetime | None, "kinds": [...]}} 이다.
    알림은 (kind, report key, window) 이고 kind 는 threshold, full, reset 중 하나다."""
    events = []
    for key, report in reports.items():
        if report.get("status") != "ok":
            continue
        for window in [*report["windows"], *([report["image"]] if report.get("image") else [])]:
            slot = (*key, window["label"])
            used, reset_at = window["used"], window.get("reset_at")
            old = sent.get(slot)
            if old:
                renewed = reset_at and old["reset_at"] and reset_at > old["reset_at"] + RESET_SLACK
                if renewed or (not (reset_at and old["reset_at"]) and used < threshold):
                    events.append(("reset", key, window))
                    del sent[slot]
                    old = None
            kinds = old["kinds"] if old else []
            kind = "full" if used >= 100 and "full" not in kinds else "threshold" if used >= threshold and not kinds else None
            if kind:
                events.append((kind, key, window))
                sent[slot] = {"reset_at": reset_at, "kinds": ["threshold", "full"] if kind == "full" else ["threshold"]}
    return events
