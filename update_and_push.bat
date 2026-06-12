@echo off
rem Daily auto-update: fetch SaaS cases, push to GitHub Pages.
rem Scheduled task: SaaSCasesDailyUpdate (17:30 daily)
chcp 65001 >nul
cd /d "%~dp0"
python fetch_saas_cases.py >> update.log 2>&1
git add cases.js
git commit -m "auto-update cases %date% %time%" >> update.log 2>&1
git push origin main >> update.log 2>&1
