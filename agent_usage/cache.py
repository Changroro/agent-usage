import json
import os
from datetime import datetime
from pathlib import Path

# 저장 형식이 바뀌면 올린다. 다른 버전의 캐시는 버리고 새로 조회한다.
VERSION = 2
CACHE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "agent-usage" / "reports.json"


def encode(value):
    if isinstance(value, datetime):
        return {"$time": value.isoformat()}
    raise TypeError(f"cannot cache {type(value).__name__}")


def decode(value):
    return datetime.fromisoformat(value["$time"]) if value.keys() == {"$time"} else value


def save(reports, backoff, sent, path=CACHE_PATH):
    """마지막 사용량, 429 대기 상태, 보낸 알림. 다시 켜도 바로 보이고 갱신 주기 안에서는 다시 조회하지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": VERSION, "reports": {"|".join(key): report for key, report in reports.items()},
            "backoff": {"|".join(key): value for key, value in backoff.items() if value},
            "alerts": {"|".join(key): value for key, value in sent.items()}}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, default=encode))
    temporary.replace(path)


def load(path=CACHE_PATH):
    if not path.exists():
        return {}, {}, {}
    data = json.loads(path.read_text(), object_hook=decode)
    if data.get("version") != VERSION:
        return {}, {}, {}
    return ({tuple(key.split("|", 1)): report for key, report in data["reports"].items()},
            {tuple(key.split("|", 1)): tuple(value) for key, value in data["backoff"].items()},
            {tuple(key.split("|", 2)): value for key, value in data.get("alerts", {}).items()})
