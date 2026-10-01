"""네이버 자동완성 → Claude 1회 호출로 세부 주제 3개 + PubMed 영문 검색어 추천."""
import asyncio

import httpx

from services import generator, naver_keyword

AUTOCOMPLETE_URL = "https://ac.search.naver.com/nx/ac"
API_MODEL = "claude-haiku-4-5"  # 짧은 분류 작업이라 가장 빠르고 싼 모델
CLI_MODEL = "haiku"

SCHEMA = {
    "type": "object",
    "properties": {
        "disease_en": {"type": "string"},
        "subtopics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "search_keyword": {"type": "string"},
                    "intent": {"type": "string"},
                    "pubmed_query": {"type": "string"},
                },
                "required": ["topic", "search_keyword", "intent", "pubmed_query"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["disease_en", "subtopics"],
    "additionalProperties": False,
}

SYSTEM = """당신은 병원 블로그 콘텐츠 기획자입니다. 네이버 검색어 후보를 보고,
병원 블로그 글로 쓰기 좋은 세부 주제 3개를 고릅니다.

- 검색량이 있으면 많은 쪽을 우선하되, 환자가 진료 전에 실제로 궁금해할 주제를 고릅니다.
- 3개는 서로 겹치지 않게 고릅니다(예: '증세'와 '증상'은 하나로).
- 병원 블로그와 무관한 주제(연예인, 뉴스, 보험 청구, 병역 판정 등)는 제외합니다.
- 후보에 좋은 주제가 3개가 안 되면, 환자들이 흔히 궁금해하는 주제로 채웁니다.
- topic: 짧은 한국어 세부 주제(예: 증세, 수술, 재활 운동)
- search_keyword: 사람들이 실제 검색할 형태(예: 허리디스크 증세)
- intent: 이 검색을 하는 사람이 알고 싶은 것 한 문장
- pubmed_query: 이 주제의 근거 논문을 찾을 PubMed 영문 검색식.
  질환명 AND (주제 관련 용어 OR ...) 형태. 예: lumbar disc herniation AND (symptoms OR clinical presentation)
- disease_en: 질환의 표준 영문명(예: lumbar disc herniation)"""


async def get_naver_autocomplete(keyword: str, limit: int = 10) -> list[str]:
    """네이버 자동완성 검색어. 비공식 엔드포인트라 실패하면 빈 목록."""
    # ponytail: 비공식 API. 막히면 검색광고 연관 키워드만으로 동작
    params = {"con": "1", "frm": "nv", "ans": "2", "r_format": "json", "r_enc": "UTF-8",
              "r_unicode": "0", "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "100"}
    seen: list[str] = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for q in (keyword, keyword + " "):  # 뒤에 공백을 붙이면 다른 후보가 더 나온다
            try:
                r = await client.get(AUTOCOMPLETE_URL, params={**params, "q": q})
                items = r.json()["items"][0]
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                continue
            for item in items:
                word = item[0].strip()
                if word and word.replace(" ", "") != keyword.replace(" ", "") and word not in seen:
                    seen.append(word)
    return seen[:limit]


async def suggest_subtopics(keyword: str) -> dict:
    candidates = await get_naver_autocomplete(keyword)
    volumes: dict[str, str] = {}
    if naver_keyword.is_configured():
        try:
            for row in await naver_keyword.related_keywords(keyword, limit=20):
                volumes[row["keyword"]] = row["label"]
        except httpx.HTTPError:
            pass

    lines = [f"- {c}" + (f" (월 검색량 {volumes[c.replace(' ', '')]})" if c.replace(" ", "") in volumes else "")
             for c in candidates]
    lines += [f"- {k} (월 검색량 {v})" for k, v in volumes.items() if k not in {c.replace(" ", "") for c in candidates}]
    prompt = f"메인 키워드: {keyword}\n\n<candidates>\n" + ("\n".join(lines) or "(후보 없음)") + "\n</candidates>"

    data, cost = await asyncio.to_thread(generator.ask_json, prompt, SYSTEM, SCHEMA, API_MODEL, CLI_MODEL)
    return {"candidates": candidates, "disease_en": data["disease_en"],
            "subtopics": data["subtopics"][:3], "api_equivalent_usd": cost}
