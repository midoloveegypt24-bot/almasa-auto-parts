@echo off
chcp 65001 >nul
title الحفاظ على متجر الماسة أونلاين 24 ساعة
color 0B

echo ===================================================================
echo   متجر الماسة لقطع غيار السيارات — تشغيل دائم 24 ساعة
echo   رابط مباشر للجمهور بدون IP وبدون باسورد
echo ===================================================================
echo.

:LOOP
echo [*] فحص خادم Flask...
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I "python.exe" >NUL
if %errorlevel% neq 0 (
    echo [*] تشغيل السيرفر...
    start /B python "C:\Users\windows10\.gemini\antigravity\scratch\almasa-auto-parts\app.py"
    timeout /t 3 /nobreak >nul
)

echo [*] تشغيل النفق المباشر المفتوح للجمهور...
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -i "%USERPROFILE%\.ssh\id_rsa" -R 80:127.0.0.1:5000 nokey@localhost.run

echo.
echo [!] حدث انقطاع في الاتصال، إعادة التوصيل التلقائي خلال 3 ثوان...
timeout /t 3 /nobreak >nul
goto LOOP
