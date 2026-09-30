"""Claude로 네이버 블로그용 병원 글 생성.

ANTHROPIC_API_KEY가 있으면 API(유료), 없으면 이 PC의 Claude Code 구독을 사용.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import anthropic

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """당신은 진료실에서 매일 환자를 만나는 병원 원장입니다. 진료가 끝난 저녁,
오늘 환자들에게 못다 한 이야기를 블로그 칼럼으로 씁니다. 정보를 정리한 보고서가 아니라,
한 사람의 의사가 자기 생각과 경험을 담아 이야기하듯 쓰는 글입니다.

[목소리]
- 1인칭("저는", "제가 진료실에서")으로 씁니다. 의사로서의 의견과 관점을 분명히 드러냅니다.
  예: "솔직히 저는 이 부분이 제일 안타깝습니다." "이건 꼭 말씀드리고 싶었어요."
- 말하듯이 씁니다. "~거든요", "~더라고요", "~잖아요" 같은 구어체를 섞되 품위는 지킵니다.
- 문장 길이를 일부러 들쭉날쭉하게 씁니다. 긴 설명 뒤에 짧은 한 문장. 그런 리듬이 사람 글입니다.
- 도입은 진료실에서 자주 듣는 한마디나 흔한 장면으로 시작합니다.
  예: "원장님, 저 디스크 터진 거 맞죠?" 진료실 문을 열자마자 이렇게 묻는 분이 꽤 많습니다.
  (특정 환자의 치료 결과나 후기처럼 쓰지 말고, 누구나 겪는 일반적인 장면으로만 씁니다.)
- 전문 용어는 처음 나올 때 쉬운 말로 풀되, 사전처럼 정의하지 말고 대화하듯 설명합니다.
- 흔한 오해 하나를 짚고 바로잡는 대목을 넣습니다. 칼럼의 중심이 되는 부분입니다.

[피할 것 - AI가 쓴 티가 나는 표현]
- "오늘은 ~에 대해 알아보겠습니다", "차근차근 정리해 드릴게요", "~에 대해 살펴볼까요?"
- "결론적으로", "요약하자면", "이처럼", "다양한", "중요한 역할을 합니다", "도움이 될 수 있습니다" 반복
- 모든 문단을 "~할 수 있습니다"로 끝내는 흐지부지한 말투. 의사로서 말할 수 있는 건 단정하게 말합니다.
- 항목 세 개씩 딱딱 맞춘 나열, 매 섹션마다 글머리표 목록. 목록은 글 전체에서 한 번 이하.
- "~란 무엇인가요?", "증상", "진단", "치료", "자주 묻는 질문"처럼 교과서식 소제목과 Q&A 블록.
- 마지막에 본문을 다시 요약하는 문단, 이모지, 느낌표 남발.

[소제목]
- <h2>는 3~4개, 칼럼의 흐름을 보여주는 문장형으로 씁니다.
  예: "사진에 디스크가 보여도, 범인이 아닐 수 있습니다" / "누워만 있는 게 답은 아니더라고요"
- <h3>는 한 <h2> 안에서 이야기가 두 갈래로 나뉠 때만 씁니다.

[논문 인용]
- 별도의 "최근 연구" 섹션을 만들지 말고, 이야기 흐름 속에서 근거로 자연스럽게 꺼냅니다.
  예: "2025년에 Frontiers in Medicine에 실린 메타분석을 보면요, ..."
- 저널명과 연도를 밝히고, 제공된 요약에 있는 내용만 씁니다.

[네이버 블로그 SEO]
- 메인 키워드를 제목, 첫 문단, 첫 번째 <h2> 근처, 마지막 문단에 자연스럽게 넣습니다.
- 연관 키워드는 본문에 억지스럽지 않게 녹입니다. 같은 단어를 반복해 채우지 않습니다.
- 본문 분량은 공백 포함 2,000~3,000자(<benchmark>가 있으면 그 분량을 따릅니다). 모바일 가독성을 위해 한 문단은 1~4문장.

[형식] HTML 조각만 출력합니다(<html>, <body>, 마크다운, 코드펜스 금지).
<h1>제목</h1>으로 시작합니다. 제목도 칼럼처럼 씁니다(예: "허리디스크, MRI 사진보다 중요한 것").
사용 가능 태그: h1, h2, h3, p, ul, li, strong, blockquote.
마무리는 요약 대신, 원장으로서 독자에게 건네는 한두 마디로 끝냅니다.

[의료광고 준수 - 반드시 지킬 것]
- 치료 효과 보장, "완치", "100%", "최고", "유일" 같은 과장·단정 표현 금지.
- 다른 병원과 비교하거나 비방하지 않습니다. 치료 전후 비교, 환자 후기 형식 금지.
- 논문 내용은 제공된 요약 범위 안에서만 인용하고, 없는 수치나 연구를 만들지 않습니다.
- 특정 환자의 사례·치료 경험담을 쓰지 않습니다. 진료실 장면은 일반적인 모습으로만 씁니다.
- 증상은 개인차가 있으며 정확한 진단은 전문의 진료가 필요하다는 안내를 마지막에 넣되,
  공지문 말투가 아니라 원장의 당부처럼 씁니다."""


def build_prompt(keyword: str, related: list[dict], papers: list[dict], hospital: str = "",
                 subtopic: str = "", intent: str = "", targets: dict | None = None) -> str:
    kw_lines = "\n".join(f"- {k['keyword']} (월 검색량 {k['total']:,})" for k in related) or "- (없음)"
    paper_lines = "\n\n".join(
        f"[{i}] {p['title']} ({p['journal']}, {p['year']})\n요약: {p['summary']}"
        for i, p in enumerate(papers, 1)
    ) or "(없음 - 논문 인용 없이 작성)"
    target = f"{keyword} {subtopic}" if subtopic else keyword
    focus = f"""
<search_intent>
이 글은 "{target}"을(를) 검색한 사람을 위한 글입니다. 그 사람이 알고 싶은 것은 "{subtopic}"입니다.
{f"검색 의도: {intent}" if intent else ""}
- 도입 세 문단 안에 그 궁금증에 대한 원장의 솔직한 답을 먼저 줍니다.
- 글 전체를 이 주제에 집중합니다. {keyword} 자체의 일반 설명은 이해에 필요한 만큼만 짧게 씁니다.
- 제목과 첫 문단에 "{target}"을 자연스럽게 넣습니다. 검색어에 '완치'처럼 광고 금지 표현이 있으면
  질문 형태로만 쓰고, 효과를 보장하지 말고 의학적으로 정직하게 답합니다.
</search_intent>
""" if subtopic else ""
    return f"""메인 키워드: {target}
병원명: {hospital or '(언급하지 않음)'}
{focus}{benchmark_block(keyword, targets)}
<related_keywords>
{kw_lines}
</related_keywords>

<papers>
{paper_lines}
</papers>

위 자료로 네이버 블로그 글을 작성해 주세요."""


def benchmark_block(keyword: str, t: dict | None) -> str:
    """네이버 상위 글 기준. 말투·의료광고 규칙보다 우선하지 않음."""
    if not t:
        return ""
    rules = []
    if t.get("chars"):
        # "약 N자"만 주면 짧게 쓰는 경향이 있어 최소 분량을 못박음
        rules.append(f"- 분량: 공백 포함 최소 {round(t['chars'] * 0.95):,}자, 목표 {t['chars']:,}자. "
                     "짧으면 상위 글보다 불리합니다. 분량이 모자라면 오해 바로잡기나 생활 속 장면을 한 대목 더 씁니다.")
    if t.get("keyword_count"):
        rules.append(f"- 메인 키워드 \"{keyword}\"을(를) 제목 포함 본문 전체에 약 {t['keyword_count']}회 자연스럽게 씁니다.")
    if t.get("images"):
        rules.append(f"- 사진이 들어갈 자리 {t['images']}곳을 흐름에 맞게 표시합니다. 형식: "
                     f"<p>📷 사진 자리 1: 넣을 사진 설명</p> (번호를 1부터 매김. 이 표시는 분량에 넣지 않음. 치료 전후·환자 사진은 제안 금지)")
    if t.get("title"):
        rules.append(f"- 제목(<h1>)은 정확히 \"{t['title']}\"로 씁니다.")
    elif t.get("title_pattern"):
        rules.append(f"- 제목은 \"{keyword}\"로 시작하고, 구체적인 증상·상황 + 질문형으로 끝냅니다.")
    if not rules:
        return ""
    return ("\n<benchmark>\n네이버 블로그 검색 상위 글에 맞춘 기준입니다. 목소리·의료광고 규칙은 그대로 지킵니다.\n"
            + "\n".join(rules) + "\n</benchmark>\n")


def _via_api(prompt: str) -> tuple[str, float | None]:
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        # 의료 주제라 안전 분류기 거절 시 서버가 다른 모델로 자동 재시도
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude가 요청을 거절했습니다. 키워드를 바꿔 다시 시도해 주세요.")
    return "".join(b.text for b in msg.content if b.type == "text"), None


def run_claude_code(prompt: str, system: str, model: str | None = None, schema: dict | None = None) -> dict:
    """API 키 없이 이 PC에 로그인된 Claude Code 구독으로 호출 (claude -p). CLI의 JSON 결과를 그대로 반환."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code(claude)가 설치돼 있지 않습니다. .env에 ANTHROPIC_API_KEY를 넣어 주세요.")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE") and k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    cmd = [exe, "-p", "--output-format", "json", "--system-prompt", system,
           # 도구·플러그인·훅 없이 순수 텍스트 생성만 (사용자 전역 설정 영향 차단)
           "--tools", "", "--setting-sources", "project", "--disable-slash-commands",
           "--strict-mcp-config", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
        env=env, cwd=Path(__file__).parent, timeout=600,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude Code 실행 실패: {(proc.stderr or proc.stdout)[:300]}")
    if out.get("is_error"):
        raise RuntimeError(f"Claude Code 오류: {out.get('result', '')[:300]}")
    # total_cost_usd: 같은 요청을 API로 했다면 들었을 금액(구독에선 청구 안 됨)
    return out


def ask_json(prompt: str, system: str, schema: dict, api_model: str = "claude-haiku-4-5",
             cli_model: str = "haiku") -> tuple[dict, float | None]:
    """짧은 JSON 응답용 호출. API 키가 있으면 API, 없으면 Claude Code 구독."""
    if os.getenv("ANTHROPIC_API_KEY"):
        msg = anthropic.Anthropic().messages.create(
            model=api_model, max_tokens=2000, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        return json.loads(next(b.text for b in msg.content if b.type == "text")), None
    out = run_claude_code(prompt, system, model=cli_model, schema=schema)
    return out["structured_output"], out.get("total_cost_usd")


def generate_post(keyword: str, related: list[dict], papers: list[dict], hospital: str = "",
                  subtopic: str = "", intent: str = "", targets: dict | None = None) -> dict:
    prompt = build_prompt(keyword, related, papers, hospital, subtopic, intent, targets)
    if os.getenv("ANTHROPIC_API_KEY"):
        engine, (text, cost) = "api", _via_api(prompt)
    else:
        out = run_claude_code(prompt, SYSTEM_PROMPT)
        engine, text, cost = "claude-code", out["result"], out.get("total_cost_usd")
    html = text.strip().removeprefix("```html").removeprefix("```").removesuffix("```").strip()
    return {"html": html, "engine": engine, "api_equivalent_usd": cost}
