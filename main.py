import asyncio
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from services import benchmark, generator, keyword_pipeline, naver_keyword, pubmed  # noqa: E402  (.env 로드 후 import)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Hospital Blog Generator")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SubtopicRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=50)


class Targets(BaseModel):
    """상위글 분석에서 원장이 체크한 기준. None이면 그 항목은 적용 안 함."""
    chars: int | None = Field(None, ge=1000, le=8000)
    keyword_count: int | None = Field(None, ge=1, le=60)
    images: int | None = Field(None, ge=1, le=30)
    title: str = Field("", max_length=80)  # 추천 제목 중 고른 것
    title_pattern: bool = False


class GenerateRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=50)
    pubmed_query: str = Field(min_length=1, max_length=300)  # 영문 PubMed 검색식 (세부 주제 추천에서 받음)
    subtopic: str = Field("", max_length=30)  # 세부 주제. 비우면 키워드 전반
    intent: str = Field("", max_length=200)
    hospital: str = Field("", max_length=50)
    targets: Targets | None = None
    # 보충해서 다시 쓰기: 이전 글 + 채워 넣을 소주제
    revise_html: str = Field("", max_length=40000)
    supplement: list[str] = Field([], max_length=6)


class TopPost(BaseModel):
    rank: int
    title: str = Field(max_length=200)
    text: str = Field(max_length=4000)


class CompareRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=50)
    my_text: str = Field(min_length=100, max_length=20000)
    posts: list[TopPost] = Field(min_length=1, max_length=10)


@app.get("/")
def index():
    # 브라우저가 옛 화면을 캐시해 새 기능이 안 보이는 일 방지
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"ok": True, "naver_configured": naver_keyword.is_configured()}


@app.post("/api/subtopics")
async def subtopics(req: SubtopicRequest):
    try:
        return await keyword_pipeline.suggest_subtopics(req.keyword.strip())
    except Exception as e:
        raise HTTPException(502, f"세부 주제 추천 실패: {e}")


@app.post("/api/benchmark")
async def bench(req: SubtopicRequest):
    try:
        return await benchmark.analyze(req.keyword.strip())
    except Exception as e:
        raise HTTPException(502, f"상위글 분석 실패: {e}")


@app.post("/api/compare")
async def compare(req: CompareRequest):
    try:
        return await benchmark.compare(req.keyword.strip(), req.my_text, [p.model_dump() for p in req.posts])
    except Exception as e:
        raise HTTPException(502, f"내용 비교 실패: {e}")


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    warnings = []

    async def get_keywords():
        if not naver_keyword.is_configured():
            warnings.append("네이버 검색광고 API 키가 없어 연관 키워드를 건너뜀")
            return []
        try:
            return await naver_keyword.related_keywords(req.keyword)
        except httpx.HTTPError as e:
            warnings.append(f"네이버 키워드 조회 실패: {e}")
            return []

    async def get_papers():
        try:
            return await pubmed.recent_papers(req.pubmed_query)
        except httpx.HTTPError as e:
            warnings.append(f"PubMed 조회 실패: {e}")
            return []

    related, papers = await asyncio.gather(get_keywords(), get_papers())
    if not papers:
        warnings.append("조건에 맞는 최근 논문이 없어 논문 인용 없이 작성함")

    try:
        # 동기 호출이라 스레드로 넘겨 이벤트 루프를 막지 않음
        post = await asyncio.to_thread(generator.generate_post, req.keyword, related, papers,
                                       req.hospital, req.subtopic, req.intent,
                                       req.targets.model_dump() if req.targets else None,
                                       req.revise_html, req.supplement)
    except Exception as e:
        raise HTTPException(502, f"글 생성 실패: {e}")

    return {**post, "keywords": related, "papers": papers, "warnings": warnings}
