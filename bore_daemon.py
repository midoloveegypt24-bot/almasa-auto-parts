"""
مراقب النفق المباشر السريع لمتجر الماسة
يقوم بتشغيل نفق bore المباشر والسريع بدون شاشات سوداء وبدون كلمات مرور
ويعيد الاتصال فوراً وتلقائياً على نفس المنفذ
"""
import subprocess
import time
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BORE_PATH = r"C:\Users\windows10\bore\bore.exe"
FIXED_PORT = 5729

def run_bore():
    cmd = [BORE_PATH, "local", "5000", "--to", "bore.pub", "--port", str(FIXED_PORT)]
    print(f"[*] تشغيل نفق bore المباشر على المنفذ {FIXED_PORT}...")
    
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    
    for line in iter(proc.stdout.readline, ''):
        line_clean = line.strip()
        print(line_clean)
        if "listening at" in line_clean:
            print("\n" + "=" * 60)
            print("  ✅ المتجر متصل ومتاح للعالم مباشرة وبدون شاشة NO TUNNEL!")
            print(f"  🌐 الرابط: http://bore.pub:{FIXED_PORT}")
            print("=" * 60 + "\n")
            
    proc.wait()
    print("⚠️ انقطع الاتصال بنفق bore، جارٍ إعادة التوصيل بعد ثانيتين...")
    time.sleep(2)

if __name__ == '__main__':
    while True:
        try:
            run_bore()
        except Exception as e:
            print("خطأ:", e)
            time.sleep(3)
