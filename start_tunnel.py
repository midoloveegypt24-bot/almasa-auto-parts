"""
Almasa Auto Parts — Public URL Tunnel
يفتح نفقاً عاماً باستخدام pyngrok لمشاركة الموقع مع العالم
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os
import time
import threading
from pyngrok import ngrok, conf

# Configure pyngrok to use local ngrok binary path if available
# pyngrok will auto-download ngrok if not present
print("=" * 60)
print("  ALMASA AUTO PARTS — تشغيل النفق العام")
print("  جارٍ تجهيز الرابط العام للموقع...")
print("=" * 60)

# Start ngrok tunnel on port 5000
try:
    # Set a custom path for ngrok binary to avoid Windows Defender issues
    ngrok_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "pyngrok", "ngrok.exe")
    
    # Open HTTP tunnel
    tunnel = ngrok.connect(5000, "http", bind_tls=True)
    public_url = tunnel.public_url
    
    print()
    print("=" * 60)
    print("  ✅ الموقع متاح للعامة الآن!")
    print("=" * 60)
    print()
    print(f"  🌐 رابط الموقع العام:")
    print(f"  {public_url}")
    print()
    print(f"  📱 شارك هذا الرابط مع أي شخص في العالم!")
    print(f"  🔒 الرابط آمن (HTTPS)")
    print()
    print("  ⚠️  ملاحظة: الرابط يعمل طالما هذا البرنامج شغّال.")
    print("  لإيقاف النفق: اضغط Ctrl+C")
    print("=" * 60)
    
    # Save URL to file for reference
    with open("public_url.txt", "w", encoding="utf-8") as f:
        f.write(f"الرابط العام لموقع الماسة:\n{public_url}\n")
    
    print(f"\n  💾 تم حفظ الرابط في ملف: public_url.txt")
    print()
    
    # Keep running
    try:
        while True:
            time.sleep(60)
            # Verify tunnel still active
            tunnels = ngrok.get_tunnels()
            if tunnels:
                print(f"  ✅ [Online] الرابط العام نشط: {public_url}")
            else:
                print("  ⚠️  النفق توقف، إعادة المحاولة...")
                break
    except KeyboardInterrupt:
        print("\n  تم إيقاف النفق.")
        ngrok.kill()

except Exception as e:
    print(f"\n  ❌ خطأ: {e}")
    print()
    print("  السبب المحتمل: ngrok يحتاج تسجيل مجاني للحصول على رابط ثابت.")
    print("  الحل البديل: راجع التعليمات أدناه.")
    raise
