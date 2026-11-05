"""
خدمة الحفاظ التلقائي على النفق العام لمتجر الماسة
تقوم بإبقاء الرابط نشطاً ومتاحاً 24 ساعة بدون انقطاع
وتعيد الاتصال فوراً في حال حدوث أي انقطاع في الإنترنت
"""
import subprocess
import time
import re
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LOG_FILE = os.path.join(os.path.dirname(__file__), "current_live_url.txt")
RESTART_BAT = os.path.join(os.path.dirname(__file__), "public_url.txt")

def start_tunnel():
    cmd = [
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'ExitOnForwardFailure=yes',
        '-R', '80:127.0.0.1:5000',
        'nokey@localhost.run'
    ]
    
    print("=====================================================")
    print("  بدء تشغيل النفق العام المباشر (24 ساعة بدون IP)...")
    print("=====================================================")
    
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    
    assigned_url = None
    for line in iter(proc.stdout.readline, ''):
        line_clean = line.strip()
        print(line_clean)
        
        # Match URL pattern like: https://xxxx.lhr.life
        match = re.search(r'https://[a-zA-Z0-9\-_]+\.lhr\.life', line_clean)
        if match:
            assigned_url = match.group(0)
            print("\n" + "=" * 60)
            print("  ✅ تم تفعيل الرابط العام المباشر بنجاح!")
            print(f"  🌐 الرابط: {assigned_url}")
            print("  ✨ يعمل مباشرة وبدون أي كلمة سر أو IP!")
            print("=" * 60 + "\n")
            
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write(assigned_url)
            
            with open(RESTART_BAT, "w", encoding="utf-8") as f:
                f.write(f"رابط متجر الماسة المباشر الحالي:\n{assigned_url}\n")
    
    proc.wait()
    print("⚠️ انقطع الاتصال، جارٍ إعادة الاتصال التلقائي خلال 5 ثوان...")
    time.sleep(5)

if __name__ == '__main__':
    while True:
        try:
            start_tunnel()
        except Exception as e:
            print(f"خطأ: {e}")
            time.sleep(5)
