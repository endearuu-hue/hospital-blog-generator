"""매일 순위 추적: 등록한 키워드마다 네이버 검색 화면을 캡처(serp_proof)해 쌓고, 날짜별 순위 표로 보여 준다.
윈도우 작업 스케줄러가 매일 `python -m services.tracker`로 실행한다(track_task.ps1로 등록)."""
import json
import sys
import time
from datetime import datetime

from services import serp_proof

ROOT = serp_proof.PROOF_DIR.parent
TRACK_FILE = ROOT / "tracked.json"
LOG = ROOT / "track.log"
DEPTH = 10  # 추적은 10위까지 (증명 버튼은 5위)
# ponytail: 캡처 이미지는 하루 키워드당 약 2MB라 60일 지난 추적 이미지만 지움. 순위 기록(JSON)은 계속 남김
KEEP_IMAGE_DAYS = 60


def keywords() -> list[str]:
    try:
        return json.loads(TRACK_FILE.read_text(encoding="utf-8"))["keywords"]
    except FileNotFoundError:
        return []


def save(kws: list[str]):
    TRACK_FILE.write_text(json.dumps({"keywords": kws}, ensure_ascii=False, indent=2), encoding="utf-8")


def records(keyword: str) -> list[dict]:
    """이 키워드의 추적 캡처 기록, 오래된 순."""
    out = []
    for f in sorted(serp_proof.PROOF_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if d.get("keyword") == keyword and d.get("source") == "track":
            out.append(d)
    return out


def history(recs: list[dict], basis: str, days: int = 30) -> dict:
    """날짜(하루 1번, 그날 마지막 캡처) × 글 → 순위 표. 최근 순위가 높은 글부터."""
    by_day = {}
    for r in recs:
        by_day[r["captured_at"][:10]] = r
    dates = sorted(by_day)[-days:]
    rows = {}
    for i, day in enumerate(dates):
        pg = by_day[day]["pages"].get(basis)
        for p in (pg or {}).get("posts", []):
            row = rows.setdefault(p["url"], {"url": p["url"], "title": p["title"], "ranks": [None] * len(dates)})
            row["ranks"][i] = p["rank"]
    last = lambda r: next((x for x in reversed(r["ranks"]) if x), 99)  # noqa: E731
    shots = [{k: v["image"] for k, v in by_day[d]["pages"].items()} for d in dates]
    return {"dates": dates, "shots": shots, "rows": sorted(rows.values(), key=lambda r: (r["ranks"][-1] is None, last(r)))}


def cleanup():
    cutoff = time.time() - KEEP_IMAGE_DAYS * 86400
    for f in serp_proof.PROOF_DIR.glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            j = f.with_name(f.name.rsplit("_", 1)[0] + ".json")
            if j.exists() and '"source": "track"' in j.read_text(encoding="utf-8"):
                f.unlink()


def log(msg: str):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def run_all():
    kws = keywords()
    log(f"시작: 키워드 {len(kws)}개")
    for kw in kws:
        for attempt in (1, 2):  # 네이버가 가끔 느려 한 번 더 시도
            try:
                serp_proof.capture(kw, DEPTH, "track")
                log(f"완료: {kw}")
                break
            except Exception as e:  # 한 키워드가 실패해도 나머지는 계속
                log(f"실패({attempt}): {kw} {e!r}")
    cleanup()


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        mk = lambda day, urls: {"captured_at": f"{day}T09:00:00+09:00",  # noqa: E731
                                "pages": {"blog": {"image": "/x.jpg", "posts": [{"rank": i, "url": u, "title": u} for i, u in enumerate(urls, 1)]}}}
        h = history([mk("2026-10-01", ["a", "b"]), mk("2026-10-02", ["x", "a"]), mk("2026-10-02", ["b", "a"])], "blog")
        assert h["dates"] == ["2026-10-01", "2026-10-02"], h  # 같은 날은 마지막 캡처만
        assert [(r["url"], r["ranks"]) for r in h["rows"]] == [("b", [2, 1]), ("a", [1, 2])], h
        assert history([mk("2026-10-01", ["a"]), mk("2026-10-02", ["b"])], "blog")["rows"][1]["ranks"] == [1, None]
        print("ok")
    else:
        run_all()
