import asyncio
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from services import generator, keyword_pipeline, naver_keyword, pubmed  # noqa: E402  (.env 로드 후 import)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Hospital Blog Generator")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SubtopicRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=50)


class GenerateRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=50)
    pubmed_query: str = Field(min_length=1, max_length=300)  # 영문 PubMed 검색식 (세부 주제 추천에서 받음)
    subtopic: str = Field("", max_length=30)  # 세부 주제. 비우면 키워드 전반
    intent: str = Field("", max_length=200)
    hospital: str = Field("", max_length=50)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "naver_configured": naver_keyword.is_configured()}


@app.post("/api/subtopics")
async def subtopics(req: SubtopicRequest):
    try:
        return await keyword_pipeline.suggest_subtopics(req.keyword.strip())
    except Exception as e:
        raise HTTPException(502, f"세부 주제 추천 실패: {e}")


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
                                       req.hospital, req.subtopic, req.intent)
    except Exception as e:
        raise HTTPException(502, f"글 생성 실패: {e}")

    return {**post, "keywords": related, "papers": papers, "warnings": warnings}
