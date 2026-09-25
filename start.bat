@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 병원 블로그 생성기를 켭니다. 이 창을 닫으면 서버도 꺼집니다.
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn main:app --port 8000
pause
