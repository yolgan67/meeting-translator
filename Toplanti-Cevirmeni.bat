@echo off
rem Canli Toplanti Cevirmeni - cift tiklayarak baslat
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Sanal ortam bulunamadi: .venv
  echo Kurulum icin README.md dosyasina bak.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m src.main %*
if errorlevel 1 pause
