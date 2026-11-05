@echo off
chcp 65001 >nul
title تشغيل متجر الماسة لقطع غيار السيارات والنفق العام
color 0A

echo ===================================================================
echo   متجر الماسة لقطع غيار السيارات — الماسة اختيارك المضمون
echo   تشغيل السيرفر والنفق العام للإنترنت (Live Online)
echo ===================================================================
echo.

set PATH=C:\Program Files\nodejs;%APPDATA%\npm;%PATH%

echo [*] التحقق من تشغيل خادم Flask...
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I "python.exe" >NUL
if %errorlevel% neq 0 (
    echo [*] جارٍ تشغيل خادم الماسة...
    start /B python "C:\Users\windows10\.gemini\antigravity\scratch\almasa-auto-parts\app.py"
    timeout /t 3 /nobreak >nul
) else (
    echo [OK] خادم Flask يعمل بنشاط.
)

echo.
echo ===================================================================
echo   🌐 رابط المتجر العام للإنترنت:
echo   https://almasa-parts.loca.lt
echo.
echo   🔑 رمز المرور للزوار أول مرة (Tunnel Password):
echo   197.34.120.143
echo ===================================================================
echo.
echo [*] جارٍ استمرار تشغيل النفق... (لا تغلق هذه النافذة طالما تريد إبقاء الموقع أونلاين)
echo.

"C:\Program Files\nodejs\node.exe" "%APPDATA%\npm\node_modules\localtunnel\bin\lt.js" --port 5000 --subdomain almasa-parts

pause
