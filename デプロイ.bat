@echo off
chcp 65001 > nul
echo.
echo ========================================
echo  万世ぶーちゃん - GitHub デプロイ
echo ========================================
echo.

cd /d "%~dp0"

git add app.py requirements.txt
git status

echo.
set /p MSG="コミットメッセージを入力（Enterで「Update」）: "
if "%MSG%"=="" set MSG=Update app.py

git commit -m "%MSG%"
git push

echo.
echo ========================================
echo  完了！約2分でStreamlit Cloudに反映されます
echo  https://manseibuuchan-app-d3rfcc9r2uefei5ndhv58t.streamlit.app/
echo ========================================
echo.
pause
