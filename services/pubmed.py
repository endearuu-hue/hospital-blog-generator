"""PubMed E-utilities - 최신 논문 초록 조회 + 요약."""
import os
import re
import xml.etree.ElementTree as ET

import httpx

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _common_params() -> dict:
    p = {"tool": "hospital-blog"}
    if os.getenv("NCBI_API_KEY"):
        p["api_key"] = os.environ["NCBI_API_KEY"]
    if os.getenv("NCBI_EMAIL"):
        p["email"] = os.environ["NCBI_EMAIL"]
    return p


def summarize_abstract(sections: list[tuple[str, str]], max_sentences: int = 3) -> str:
    """구조화 초록이면 결론(CONCLUSION) 섹션, 아니면 마지막 문장들을 요약으로 쓴다."""
    # ponytail: 추출 요약. 생성 단계에서 Claude가 어차피 재가공하므로 별도 LLM 호출은 생략
    for label, text in sections:
        if "CONCLUSION" in label.upper():
            return text
    full = " ".join(text for _, text in sections)
    sentences = re.split(r"(?<=[.!?])\s+", full.strip())
    return " ".join(sentences[-max_sentences:])


def parse_articles(xml_text: str) -> list[dict]:
    papers = []
    for art in ET.fromstring(xml_text).iter("PubmedArticle"):
        sections = [
            (el.get("Label", ""), "".join(el.itertext()).strip())
            for el in art.iter("AbstractText")
        ]
        if not sections:
            continue
        pmid = art.findtext(".//PMID")
        papers.append({
            "pmid": pmid,
            "title": "".join(art.find(".//ArticleTitle").itertext()).strip(),
            "journal": art.findtext(".//Journal/Title", ""),
            "year": art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate", "")[:4],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "abstract": "\n".join(f"{l}: {t}" if l else t for l, t in sections),
            "summary": summarize_abstract(sections),
        })
    return papers


async def recent_papers(query: str, count: int = 3) -> list[dict]:
    """영문 PubMed 검색식으로 최근 논문 count개의 초록과 요약을 가져온다.
    예: "lumbar disc herniation AND (symptoms OR clinical presentation)" """
    term = f"({query})"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{EUTILS}/esearch.fcgi", params={
            # 최신순만 쓰면 무관한 증례보고가 섞여서, 최근 3년 리뷰·임상연구 중 관련도순
            **_common_params(), "db": "pubmed",
            "term": f"{term} AND hasabstract AND "
                    "(review[pt] OR meta-analysis[pt] OR clinical trial[pt] OR randomized controlled trial[pt])",
            "datetype": "pdat", "reldate": 1095,
            "retmax": count, "sort": "relevance", "retmode": "json",
        })
        r.raise_for_status()
        ids = r.json()["esearchresult"]["idlist"]
        if not ids:
            return []
        r = await client.get(f"{EUTILS}/efetch.fcgi", params={
            **_common_params(), "db": "pubmed", "id": ",".join(ids),
            "rettype": "abstract", "retmode": "xml",
        })
        r.raise_for_status()
    return parse_articles(r.text)


if __name__ == "__main__":
    sample = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
    <Journal><Title>J</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
    <ArticleTitle>T</ArticleTitle><Abstract>
    <AbstractText Label="BACKGROUND">Bg.</AbstractText>
    <AbstractText Label="CONCLUSIONS">It works.</AbstractText>
    </Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    p = parse_articles(sample)[0]
    assert p["summary"] == "It works." and p["year"] == "2026", p
    assert summarize_abstract([("", "A. B. C. D.")]) == "B. C. D."
    print("ok")
