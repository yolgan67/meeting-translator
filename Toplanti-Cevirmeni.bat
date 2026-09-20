@echo off
rem Canli Toplanti Cevirmeni - cift tiklayarak baslat.
rem pythonw ile baslatilir: konsol penceresi acilmaz, bu dosyayi acik
rem tutmak gerekmez. Mesajlar logs\app.log dosyasina yazilir.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Sanal ortam bulunamadi: .venv
  echo Kurulum icin README.md dosyasina bak.
  pause
  exit /b 1
)
start "Toplanti Cevirmeni" /b ".venv\Scripts\pythonw.exe" -m src.main %*
exit /b 0
