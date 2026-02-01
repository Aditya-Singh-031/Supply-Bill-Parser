"""
Configuration and environment variable management.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
INVOICES_DIR = PROJECT_ROOT / "invoices"
BILLS_JSON_DIR = PROJECT_ROOT / "bills_json"
BILLS_EXCEL_DIR = PROJECT_ROOT / "bills_excel"
DATA_SAMPLES_DIR = PROJECT_ROOT / "data_samples"

# Azure Document Intelligence
AZURE_DI_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
AZURE_DI_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "")
USE_AZURE_DI = bool(AZURE_DI_ENDPOINT and AZURE_DI_KEY)

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is required in .env file")

# LiteLLM settings
LITELLM_LOG = os.getenv("LITELLM_LOG", "False").lower() == "true"

# Model configuration
OPENAI_MODEL = "gpt-4o-2024-08-06"  # Supports structured outputs
TEMPERATURE = 0  # Deterministic for invoice extraction

# Validation settings
VALIDATION_TOLERANCE_PERCENT = float(
    os.getenv("VALIDATION_TOLERANCE_PERCENT", "0.5")
)
VALIDATION_TOLERANCE_ABSOLUTE = float(
    os.getenv("VALIDATION_TOLERANCE_ABSOLUTE", "10.0")
)

# Debug mode
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Create directories if they don't exist
for directory in [INVOICES_DIR, BILLS_JSON_DIR, BILLS_EXCEL_DIR, DATA_SAMPLES_DIR]:
    directory.mkdir(exist_ok=True)

print(f"📂 Project root: {PROJECT_ROOT}")
print(f"🔧 Using Azure DI: {USE_AZURE_DI}")
print(f"🤖 OpenAI Model: {OPENAI_MODEL}")
print(f"🔍 Debug mode: {DEBUG}")
