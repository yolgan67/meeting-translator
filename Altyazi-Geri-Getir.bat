@echo off
rem Altyazi penceresi kayboldu / gizlendiyse geri getirir ve ortalar.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.main --show
rem Mesaj okunabilsin diye kisa bekleme (timeout stdin yonlendirmesinde hata verir).
ping -n 4 127.0.0.1 >nul
