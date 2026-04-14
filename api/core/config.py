"""
API Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project paths
API_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = API_ROOT.parent

# API Settings
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# CORS Settings
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001"
).split(",")

# Force include production domains
if "https://ops.morsebiz.com" not in CORS_ORIGINS:
    CORS_ORIGINS.append("https://ops.morsebiz.com")
if "https://bills-parser.morsebiz.com" not in CORS_ORIGINS:
    CORS_ORIGINS.append("https://bills-parser.morsebiz.com")
if "https://ops-frontend.morsebiz.com" not in CORS_ORIGINS:
    CORS_ORIGINS.append("https://ops-frontend.morsebiz.com")

# Redis Settings
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Job Settings
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILES_PER_BATCH = 20
JOB_TIMEOUT = 3600  # 1 hour
JOB_CLEANUP_AFTER = 86400  # 24 hours

# Processing Settings
WORKER_PROCESSES = int(os.getenv("WORKER_PROCESSES", "4"))
ENABLE_DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# Temporary file storage
TEMP_UPLOAD_DIR = PROJECT_ROOT / "temp_uploads"
TEMP_UPLOAD_DIR.mkdir(exist_ok=True)

# Output directories (from existing config)
BILLS_JSON_DIR = PROJECT_ROOT / "bills_json"
BILLS_EXCEL_DIR = PROJECT_ROOT / "bills_excel"
BILLS_OLD_JSON_DIR = PROJECT_ROOT / "bills_old_json"
BILLS_OLD_PDF_DIR = PROJECT_ROOT / "bills_old_pdf"

# Ensure directories exist
for directory in [BILLS_JSON_DIR, BILLS_EXCEL_DIR, BILLS_OLD_JSON_DIR, BILLS_OLD_PDF_DIR]:
    directory.mkdir(exist_ok=True)
