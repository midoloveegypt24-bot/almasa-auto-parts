import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'almasa-secret-key-2026-auto-parts-secure-token')
    DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'almasa.db')
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    PRODUCT_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'products')
    RECEIPT_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'receipts')
    DESIGN_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'design')
    CATEGORY_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'categories')
    BRAND_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'brands')
    MODEL_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, 'models')
    BACKUPS_FOLDER = os.path.join(BASE_DIR, 'data', 'backups')
    
    # Business Identity
    BUSINESS_NAME_AR = "الماسة لقطع غيار السيارات"
    BUSINESS_NAME_EN = "Almasa Auto Spare Parts"
    BRAND_SLOGAN = "الماسة اختيارك المضمون في قطع الغيار ✔️"
    BUSINESS_LOCATION = "أسيوط ـ الطريق الدائري ـ المعلمين الجديدة ـ أول شارع يمين جامع الشيخ عثمان"
    BUSINESS_PHONE = "01212429139"
    WHATSAPP_NUMBER = "201212429139"
    WALLET_NUMBER = "01212429139"
    INSTAPAY_ACCOUNT = "01212429139"
    
    # Upload limits
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
    ALLOWED_BACKUP_EXTENSIONS = {'back', 'bak', 'sql', 'json'}

os.makedirs(Config.PRODUCT_IMAGES_FOLDER, exist_ok=True)
os.makedirs(Config.RECEIPT_IMAGES_FOLDER, exist_ok=True)
os.makedirs(Config.BACKUPS_FOLDER, exist_ok=True)
