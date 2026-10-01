"""네이버 검색광고 API - 연관 키워드 + 월간 검색량 조회."""
import base64
import hashlib
import hmac
import os
import time

import httpx

BASE_URL = "https://api.searchad.naver.com"


def _headers(method: str, uri: str) -> dict:
    ts = str(int(time.time() * 1000))
    secret = os.environ["NAVER_AD_SECRET_KEY"].encode()
    sig = hmac.new(secret, f"{ts}.{method}.{uri}".encode(), hashlib.sha256).digest()
    return {
        "X-Timestamp": ts,
        "X-API-KEY": os.environ["NAVER_AD_API_KEY"],
        "X-Customer": os.environ["NAVER_AD_CUSTOMER_ID"],
        "X-Signature": base64.b64encode(sig).decode(),
    }


def _to_int(v) -> int:
    # 검색량이 적으면 API가 "< 10" 문자열을 준다 → 0 으로 더하고 label 에 "10 미만"/"N 이상"으로 표시
    return v if isinstance(v, int) else 0


def _label(total: int, under10: bool) -> str:
    if total == 0:
        return "10 미만"
    return f"{total:,} 이상" if under10 else f"{total:,}"


def is_configured() -> bool:
    return all(os.getenv(k) for k in ("NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_AD_CUSTOMER_ID"))


async def related_keywords(keyword: str, limit: int = 10) -> list[dict]:
    """입력 키워드의 연관 키워드를 월간 총검색량(PC+모바일) 내림차순으로 반환."""
    uri = "/keywordstool"
    params = {"hintKeywords": keyword.replace(" ", ""), "showDetail": "1"}  # 공백 있으면 400
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(BASE_URL + uri, params=params, headers=_headers("GET", uri))
        r.raise_for_status()

    rows = []
    for item in r.json().get("keywordList", []):
        pc, mobile = _to_int(item["monthlyPcQcCnt"]), _to_int(item["monthlyMobileQcCnt"])
        rows.append({
            "keyword": item["relKeyword"],
            "pc": pc,
            "mobile": mobile,
            "total": pc + mobile,
            "label": _label(pc + mobile, not isinstance(item["monthlyPcQcCnt"], int) or not isinstance(item["monthlyMobileQcCnt"], int)),
            "competition": item.get("compIdx", ""),
        })
    rows.sort(key=lambda x: x["total"], reverse=True)
    return rows[:limit]
