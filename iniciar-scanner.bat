@echo off
:: Solicita privilégios de administrador (necessário para WinDivert)
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Roda o executável se existir, senão tenta via Python (modo desenvolvimento)
if exist "%~dp0dist\Albion Market.exe" (
    start "" "%~dp0dist\Albion Market.exe"
) else (
    python "%~dp0captura_gui.py"
)
