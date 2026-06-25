@echo off
:: Solicita privilégios de administrador (necessário para WinDivert)
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Inicia o aplicativo (Node.js sobe automaticamente dentro do Python)
python "%~dp0captura_gui.py"
