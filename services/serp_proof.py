"""네이버 검색 화면을 실제 브라우저로 열어 캡처 → 화면에 보이는 순서로 블로그 글 순위를 뽑고,
상위글 분석에 쓴 글이 정말 그 순위에 있는지 대조한다. 캡처 이미지에 검색어·시각을 찍고 해시를 남겨 증거로 씀."""
import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

PROOF_DIR = Path(__file__).resolve().parent.parent / "proofs"
KST = timezone(timedelta(hours=9))
TOP_N = 5
PAGES = {  # 키: (이름, 주소, 모바일 화면인지). 통합검색 = 메인 화면
    "main": ("통합검색(모바일)", "https://m.search.naver.com/search.naver?query={}", True),
    "blog": ("블로그탭(모바일)", "https://m.search.naver.com/search.naver?ssc=tab.m_blog.all&query={}", True),  # 생성기 상위글 분석 기준
    "pc": ("블로그탭(PC)", "https://search.naver.com/search.naver?ssc=tab.blog.all&query={}", False),  # 웹 비교기 기준
}
POST_RE = re.compile(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)")
# ponytail: 브라우저 하나씩만 띄움(PC 메모리 6GB). 동시에 여러 명이 쓰면 줄 서서 기다림
_lock = threading.Lock()

# 화면 위→아래 순서로 블로그 글(제목 링크)을 모으고, 그 자리에 순위 표시를 그려 넣음
COLLECT_JS = r"""([n, stamp]) => {
  // 위에 붙어 다니는 검색창·버튼을 제자리로 → 전체 캡처에서 표시 띠나 글을 가리지 않음
  for (const el of document.querySelectorAll("body *"))
    if (/fixed|sticky/.test(getComputedStyle(el).position)) el.style.position = "static";
  const re = /blog\.naver\.com\/([A-Za-z0-9_-]+)\/(\d+)/, seen = new Set(), out = [];
  for (const a of document.querySelectorAll('a[href*="blog.naver.com/"]')) {
    const m = a.href.match(re), r = a.getBoundingClientRect(), text = a.innerText.trim();
    // 제목 링크만: 글자가 있고 화면에 보이는 것. 사진·조회수 링크는 같은 글이라 건너뜀
    if (!m || seen.has(m[1] + "/" + m[2]) || r.height === 0 || text.length < 5) continue;
    seen.add(m[1] + "/" + m[2]);
    out.push({blog: m[1], no: m[2], title: text.split("\n")[0].slice(0, 120), y: Math.round(r.top + scrollY), bottom: Math.round(r.bottom + scrollY)});
    a.style.outline = "3px solid #e60023"; a.style.outlineOffset = "2px";
    a.insertAdjacentHTML("beforebegin", `<span style="display:inline-block;background:#e60023;color:#fff;font:700 13px sans-serif;padding:2px 6px;border-radius:4px;margin:0 4px 2px 0">${out.length}위</span>`);
    if (out.length >= n) break;
  }
  document.body.insertAdjacentHTML("afterbegin", `<div style="background:#111;color:#fff;font:600 13px/1.5 sans-serif;padding:8px 12px">${stamp}</div>`);
  return out;
}"""


def _scroll_to(page, bottom: int):
    """사진은 화면에 들어와야 불러오므로 끝까지 천천히 내렸다가 위로."""
    for y in range(0, bottom, 600):
        page.evaluate(f"scrollTo(0, {y})")
        page.wait_for_timeout(120)
    page.evaluate("scrollTo(0, 0)")
    page.wait_for_timeout(500)


def capture(keyword: str, n: int = TOP_N, source: str = "proof") -> dict:
    """source: "proof"(증명 버튼) | "track"(매일 순위 추적)."""
    now = datetime.now(KST)
    stem = f"{now:%Y%m%d-%H%M%S}_{re.sub(r'[^0-9A-Za-z가-힣]+', '-', keyword)[:30]}"
    PROOF_DIR.mkdir(exist_ok=True)
    result = {"keyword": keyword, "captured_at": now.isoformat(timespec="seconds"), "source": source, "pages": {}}
    with _lock, sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # 모바일은 해상도를 1.5배로 낮춰 파일 크기 줄임
            mobile = {**p.devices["Pixel 7"], "device_scale_factor": 1.5}
            desktop = {"viewport": {"width": 1280, "height": 900}}
            for key, (label, tpl, is_mobile) in PAGES.items():
                url = tpl.format(quote(keyword))
                page = browser.new_page(**(mobile if is_mobile else desktop), locale="ko-KR")
                page.goto(url, wait_until="networkidle", timeout=30000)
                _scroll_to(page, page.evaluate("document.body.scrollHeight"))
                stamp = f"네이버 {label} · 검색어 「{keyword}」 · {now:%Y-%m-%d %H:%M:%S} KST · 빨간 상자 = 블로그 글 순위"
                posts = page.evaluate(COLLECT_JS, [n, stamp])
                height = page.evaluate("document.body.scrollHeight")
                # 마지막 글 아래 조금까지만 자름(표시 띠가 위에 붙어 좌표가 36px쯤 밀림)
                bottom = min(height, (posts[-1]["bottom"] + 360) if posts else 3000)
                img = PROOF_DIR / f"{stem}_{key}.jpg"
                page.screenshot(path=img, full_page=True, type="jpeg", quality=70,
                                clip={"x": 0, "y": 0, "width": page.viewport_size["width"], "height": bottom})
                result["pages"][key] = {
                    "label": label, "url": url, "image": f"/proofs/{img.name}",
                    "sha256": hashlib.sha256(img.read_bytes()).hexdigest(),
                    "posts": [{"rank": i, "url": f"https://blog.naver.com/{x['blog']}/{x['no']}", "title": x["title"]}
                              for i, x in enumerate(posts, 1)],
                }
                page.close()
        finally:
            browser.close()
    (PROOF_DIR / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _key(url: str) -> str:
    m = POST_RE.search(url)
    return f"{m[1]}/{m[2]}" if m else url


def verify(captured: dict, posts: list[dict], basis: str = "blog") -> list[dict]:
    """분석한 글마다 캡처 화면별 실제 순위. 기준 화면(basis) 순위가 분석 순위와 같아야 '확인'."""
    ranks = {k: {_key(x["url"]): x["rank"] for x in pg["posts"]} for k, pg in captured["pages"].items()}
    out = []
    for p in posts:
        found = {k: r.get(_key(p["url"])) for k, r in ranks.items()}
        status = "확인" if found.get(basis) == p["rank"] else "순위 다름" if found.get(basis) else "화면에 없음"
        out.append({"rank": p["rank"], "url": p["url"], "ranks": found, "status": status})
    return out


if __name__ == "__main__":
    cap = {"pages": {"blog": {"posts": [{"rank": 1, "url": "https://blog.naver.com/a/1"}, {"rank": 2, "url": "https://blog.naver.com/b/2"}]},
                     "main": {"posts": [{"rank": 1, "url": "https://blog.naver.com/b/2"}]}}}
    v = verify(cap, [{"rank": 1, "url": "https://m.blog.naver.com/a/1"}, {"rank": 1, "url": "https://blog.naver.com/b/2"},
                     {"rank": 3, "url": "https://blog.naver.com/c/3"}])
    assert [x["status"] for x in v] == ["확인", "순위 다름", "화면에 없음"], v
    assert v[1]["ranks"]["main"] == 1 and v[0]["ranks"]["main"] is None, v
    assert verify(cap, [{"rank": 1, "url": "https://blog.naver.com/b/2"}], basis="main")[0]["status"] == "확인"
    print("ok")
