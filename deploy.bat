@echo off
chcp 65001 > nul
echo.
echo ========================================
echo  Manse-Buchan - Deploy to GitHub
echo ========================================
echo.

cd /d "%~dp0"

git add app.py requirements.txt
git status

echo.
set /p MSG=Commit message (press Enter for "Update"):
if "%MSG%"=="" set MSG=Update app.py

git commit -m "%MSG%"
git push

echo.
echo ========================================
echo  Done! Streamlit Cloud updates in ~2min
echo  https://manseibuuchan-app-d3rfcc9r2uefei5ndhv58t.streamlit.app/
echo ========================================
echo.
pause
