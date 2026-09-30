"""네이버 블로그 검색 상위 글 분석 → 새 글이 맞출 기준(분량·키워드 횟수·사진 수) + 추천 제목."""
import asyncio
import html
import re
import statistics

import httpx

from services import generator

SEARCH_URL = "https://search.naver.com/search.naver"
POST_URL = "https://m.blog.naver.com/PostView.naver"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Mobile Safari/537.36"
TOP_N = 5

SCHEMA = {
    "type": "object",
    "properties": {
        "reasons": {"type": "array", "items": {"type": "string"}},
        "titles": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reasons", "titles", "avoid", "notes"],
    "additionalProperties": False,
}

SYSTEM = """당신은 네이버 블로그 SEO와 의료광고법을 아는 병원 콘텐츠 기획자입니다.
검색 상위 블로그 글들의 수치와 도입부를 보고 짧게 분석합니다.

- reasons: 상위에 오른 공통 패턴 3~4개. 한 문장씩, 수치 근거를 넣습니다(예: "1~3위 평균 3,490자로 4~5위보다 김").
  제목 구조, 분량, 사진 수, 키워드 반복, 도입 방식 중에서 고릅니다.
- titles: 같은 패턴으로 병원 원장이 쓸 칼럼 제목 3개. 메인 키워드로 시작하고 구체적인 증상·상황 + 질문형.
  "완치", "100%", "최고", "전문병원" 같은 의료광고 금지 표현은 쓰지 않습니다.
- avoid: 상위 글에 보이지만 병원 블로그가 따라 하면 의료법상 문제가 되는 요소(전문병원 명칭, 치료 체험담,
  전후 사진, 과장 표현 등). 없으면 빈 배열. 한 줄씩 짧게.
- notes: 글마다 하나씩, 순위 순서대로. 그 글이 어떤 글인지 한두 문장(누가 쓴 어떤 형식의 글인지,
  도입·구성의 특징, 눈에 띄는 강점). 예: "약사 블로그의 제품 비교형. 요약표로 시작하고 사진 28장으로 제품을 보여 줌.\""""


def parse_search(page: str) -> list[tuple[str, str]]:
    """검색 결과 HTML에서 블로그 글 (blogId, logNo)를 노출 순서대로."""
    # 모바일 검색은 m.blog 링크, 스크립트 안 링크는 https:\/\/ 로 이스케이프돼 있어 scheme 없이 찾음
    found = re.findall(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)", page)
    return list(dict.fromkeys(found))[:TOP_N]


def parse_post(page: str, keyword: str) -> dict:
    """모바일 글 HTML에서 제목·본문 수치 추출. keyword 횟수는 띄어쓰기 무시."""
    m = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    title = html.unescape(m[1]) if m else ""
    body = page.split("se-main-container", 1)[-1].split(">", 1)[-1]
    text = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", body, flags=re.S)
    text = re.sub(r"\s+", " ", html.unescape(text).replace("​", "")).strip()
    text = text.split("공감한 사람 보러가기")[0]  # 본문 뒤 공감·댓글 영역 제거
    kw = keyword.replace(" ", "")
    return {
        "title": title,
        "chars": len(text),
        "images": len(re.findall(r'class="se-module se-module-image', body)),
        "quotes": len(re.findall(r'class="se-component se-quotation', body)),
        "keyword_count": text.replace(" ", "").count(kw),
        "keyword_in_title": kw in title.replace(" ", ""),
        "intro": text[:200],
        "text": text[:3000],  # 내용 비교용. 앞부분만으로도 다루는 소주제는 충분히 보임
        "blocks": parse_blocks(body),  # 나란히 보기용 본문
    }


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("​", "")).strip()


def parse_blocks(body: str) -> list[dict]:
    """스마트에디터 본문을 [{"t": "h"|"p"|"quote"|"img"|"table", "x": 텍스트}] 순서대로. 화면에 그대로 그림."""
    blocks = []
    for chunk in body.split('<div class="se-component ')[1:]:
        kind = chunk.split('"', 1)[0].split()[0]
        chunk = chunk.split(">", 1)[-1]  # 여는 div 태그의 속성 제거
        if kind in ("se-image", "se-imageStrip", "se-imageGroup", "se-video"):
            blocks.append({"t": "img", "x": ""})
        elif kind == "se-quotation":
            blocks.append({"t": "quote", "x": _clean(chunk)})
        elif kind == "se-sectionTitle":
            blocks.append({"t": "h", "x": _clean(chunk)})
        elif kind == "se-table":
            blocks.append({"t": "table", "x": _clean(chunk)[:300]})
        elif kind == "se-text":
            for p in re.findall(r'<p class="se-text-paragraph[^>]*>(.*?)</p>', chunk, flags=re.S):
                x = _clean(p)
                if not x:
                    continue
                # 글씨를 크게(24px 이상) 쓴 짧은 줄은 사실상 소제목
                big = re.search(r"se-fs-fs(2[4-9]|3\d)", p) and len(x) < 60
                blocks.append({"t": "h" if big else "p", "x": x})
        if "공감한 사람 보러가기" in chunk:
            break
    return blocks[:300]


def targets(posts: list[dict]) -> dict:
    """새 글이 맞출 기준. 분량·키워드 밀도는 1~3위 평균(상위권 기준), 사진은 전체 평균."""
    top = posts[:3]
    chars = round(statistics.mean(p["chars"] for p in top), -2)
    density = statistics.mean(p["keyword_count"] / max(p["chars"], 1) for p in top)
    return {
        "chars": int(chars),
        "keyword_count": max(3, round(chars * density)),
        "images": round(statistics.mean(p["images"] for p in posts)),
        "quotes": max(1, round(statistics.mean(p["quotes"] for p in top))),
    }


async def top_posts(keyword: str) -> list[dict]:
    # ponytail: 네이버 검색 HTML 스크래핑이라 페이지 구조가 바뀌면 깨짐. 그때 parse_search/parse_post만 고치면 됨
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}, follow_redirects=True) as client:
        r = await client.get(SEARCH_URL, params={"ssc": "tab.blog.all", "query": keyword})
        r.raise_for_status()
        ids = parse_search(r.text)

        async def one(rank: int, blog: str, no: str):
            try:
                p = await client.get(POST_URL, params={"blogId": blog, "logNo": no})
                p.raise_for_status()
            except httpx.HTTPError:
                return None
            return {"rank": rank, "url": f"https://blog.naver.com/{blog}/{no}", **parse_post(p.text, keyword)}

        posts = await asyncio.gather(*(one(i, b, n) for i, (b, n) in enumerate(ids, 1)))
    return [p for p in posts if p and p["chars"] > 300]  # 본문을 못 읽은 글 제외


async def analyze(keyword: str) -> dict:
    posts = await top_posts(keyword)
    if len(posts) < 3:
        raise RuntimeError("네이버 상위 글을 3개 이상 읽지 못했습니다. 잠시 후 다시 시도해 주세요.")
    lines = "\n".join(
        f"{p['rank']}위 | {p['title']} | {p['chars']}자 | 사진 {p['images']} | 인용구 {p['quotes']} | "
        f"키워드 {p['keyword_count']}회 | 본문 앞부분: {p['text'][:600]}" for p in posts)
    ai, cost = await asyncio.to_thread(generator.ask_json, f"메인 키워드: {keyword}\n\n{lines}", SYSTEM, SCHEMA)
    return {"keyword": keyword, "posts": posts, "targets": targets(posts), **ai, "api_equivalent_usd": cost}


COMPARE_SCHEMA = {
    "type": "object",
    "properties": {
        "covered": {"type": "array", "items": {"type": "string"}},
        "missing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "posts": {"type": "integer"}, "note": {"type": "string"}},
                "required": ["topic", "posts", "note"],
                "additionalProperties": False,
            },
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["covered", "missing", "strengths"],
    "additionalProperties": False,
}

COMPARE_SYSTEM = """당신은 병원 블로그 편집자입니다. 네이버 검색 상위 글들과 원장이 쓴 새 글을 내용 기준으로 비교합니다.

- covered: 상위 글도 다루고 새 글도 다룬 소주제 3~5개. 짧은 명사구.
- missing: 상위 글 2개 이상이 다루는데 새 글에는 없는 소주제. 많이 다룬 순으로 최대 4개.
  posts는 그 소주제를 다룬 상위 글 수, note는 병원 블로그에서 어떻게 다루면 되는지 한 줄.
  제품명 추천·순위, 체험담, 전후 사진, 시술 권유처럼 의료광고법상 병원이 따라 하면 안 되는 내용은 missing에 넣지 않습니다.
  제품 이야기가 필요하면 note에 "제품명 없이 성분 중심으로"처럼 적습니다.
- strengths: 새 글에만 있는 강점 1~3개(예: 논문 근거 인용, 의사 1인칭 관점). 짧게."""


async def compare(keyword: str, my_text: str, posts: list[dict]) -> dict:
    tops = "\n\n".join(f"<post rank=\"{p['rank']}\" title=\"{p['title']}\">\n{p['text']}\n</post>" for p in posts)
    prompt = f"메인 키워드: {keyword}\n\n<top_posts>\n{tops}\n</top_posts>\n\n<my_post>\n{my_text[:6000]}\n</my_post>"
    # 소주제 대조는 판단이 필요해 haiku 대신 sonnet
    data, cost = await asyncio.to_thread(generator.ask_json, prompt, COMPARE_SYSTEM, COMPARE_SCHEMA,
                                         "claude-sonnet-5-5", "sonnet")
    return {**data, "api_equivalent_usd": cost}


if __name__ == "__main__":
    post = ('<meta property="og:title" content="허리디스크 다리저림, 왜?"><div class="se-main-container">'
            '<p>허리 디스크 는 흔합니다. 허리디스크 증상</p><div class="se-module se-module-image"></div>'
            '<div class="se-component se-quotation"></div><p>공감한 사람 보러가기 허리디스크</p>')
    p = parse_post(post, "허리디스크")
    assert p["title"] == "허리디스크 다리저림, 왜?" and p["images"] == 1 and p["quotes"] == 1, p
    assert p["keyword_count"] == 2 and p["keyword_in_title"], p  # 띄어쓰기 무시, 공감 영역 제외
    assert parse_search("x https://blog.naver.com/a/1 y https://blog.naver.com/a/1 https://blog.naver.com/b_2/3") \
        == [("a", "1"), ("b_2", "3")]
    t = targets([{"chars": 3000, "keyword_count": 15, "images": 10, "quotes": 6}] * 3 + [{"chars": 1000, "keyword_count": 1, "images": 0, "quotes": 0}])
    assert t == {"chars": 3000, "keyword_count": 15, "images": 8, "quotes": 6}, t
    blocks = parse_blocks('x<div class="se-component se-text"><p class="se-text-paragraph"><span class="se-fs-fs28">소제목</span></p>'
                          '<p class="se-text-paragraph">본문 &amp; 문장</p><p class="se-text-paragraph"> </p></div>'
                          '<div class="se-component se-image"></div><div class="se-component se-quotation"><p>인용</p></div>'
                          '<div class="se-component se-horizontalLine"></div>')
    assert blocks == [{"t": "h", "x": "소제목"}, {"t": "p", "x": "본문 & 문장"}, {"t": "img", "x": ""},
                      {"t": "quote", "x": "인용"}], blocks
    print("ok")
