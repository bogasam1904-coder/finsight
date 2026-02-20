"""
Financial Statement Analyzer - FastAPI Backend
Uses Google Gemini (free) instead of Anthropic Claude
Requirements: see requirements.txt
"""

import os
import uuid
import base64
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pydantic import BaseModel, EmailStr
import motor.motor_asyncio
from jose import JWTError, jwt
from passlib.context import CryptContext
import google.generativeai as genai
import pypdf
import io

# ── Config ────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET      = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_MIN  = 60 * 24 * 7   # 7 days
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ── App & DB ──────────────────────────────────────────────────────────────────

app = FastAPI(title="FinSight - Financial Analyzer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

client       = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db           = client.finsight
users_col    = db.users
analyses_col = db.analyses

# ── Auth helpers ──────────────────────────────────────────────────────────────

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MIN)
    return jwt.encode({"sub": user_id, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await users_col.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    token: str
    user_id: str
    name: str
    email: str

class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=AuthResponse)
async def register(body: RegisterRequest):
    existing = await users_col.find_one({"email": body.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    await users_col.insert_one({
        "user_id":    user_id,
        "name":       body.name,
        "email":      body.email,
        "password":   hash_password(body.password),
        "created_at": datetime.utcnow().isoformat(),
    })
    return AuthResponse(token=create_token(user_id), user_id=user_id, name=body.name, email=body.email)


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    user = await users_col.find_one({"email": body.email})
    if not user or not verify_password(body.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return AuthResponse(
        token=create_token(user["user_id"]),
        user_id=user["user_id"],
        name=user["name"],
        email=user["email"],
    )


@app.get("/api/auth/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return UserResponse(
        user_id=current_user["user_id"],
        name=current_user["name"],
        email=current_user["email"],
    )


# ── File helpers ──────────────────────────────────────────────────────────────

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
MAX_SIZE_MB  = 10


def extract_pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return ""


# ── Gemini Analysis ───────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """You are an expert financial analyst. Analyze this financial statement and return ONLY valid JSON — no markdown, no explanation, no code fences.

The JSON must match this exact structure:
{
  "company_name": "string or null",
  "statement_type": "income_statement | balance_sheet | cash_flow | other",
  "period": "e.g. FY2023 or Q3 2024 or null",
  "currency": "USD or detected symbol",
  "summary": "2-3 sentence plain-English summary of financial health",
  "health_score": integer from 1 to 100,
  "health_label": "Excellent | Good | Fair | Poor",
  "key_metrics": [
    { "label": "string", "value": "string", "change": "string or null", "trend": "up | down | neutral" }
  ],
  "income": {
    "revenue": number or null,
    "gross_profit": number or null,
    "operating_income": number or null,
    "net_income": number or null,
    "ebitda": number or null
  },
  "ratios": {
    "gross_margin": number or null,
    "operating_margin": number or null,
    "net_margin": number or null,
    "current_ratio": number or null,
    "debt_to_equity": number or null,
    "roe": number or null
  },
  "highlights": ["string", "string"],
  "risks": ["string", "string"]
}

Rules:
- Include 4-6 key_metrics with the most important numbers
- All monetary values in base units (dollars, not thousands)
- Use null for any value you cannot determine
- Return ONLY the JSON object, nothing else
"""


async def analyze_with_gemini(content: bytes, mime_type: str, filename: str) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")  # free tier model

    parts: list[Any] = []

    if mime_type == "application/pdf":
        text = extract_pdf_text(content)
        if len(text) > 200:
            parts.append(f"Filename: {filename}\n\nExtracted text from PDF:\n{text[:15000]}")
        else:
            parts.append({
                "inline_data": {
                    "mime_type": "application/pdf",
                    "data": base64.b64encode(content).decode(),
                }
            })
    else:
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(content).decode(),
            }
        })

    parts.append(ANALYSIS_PROMPT)

    try:
        response = model.generate_content(parts)
        raw = response.text.strip()
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(e)}")

    # Strip markdown fences if present
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except Exception:
        logger.error(f"Gemini returned invalid JSON: {raw[:500]}")
        raise HTTPException(status_code=500, detail="AI returned malformed response — please try again")


# ── Analysis routes ───────────────────────────────────────────────────────────

@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_SIZE_MB} MB)")

    analysis_id = str(uuid.uuid4())
    file_type   = "pdf" if file.content_type == "application/pdf" else "image"

    await analyses_col.insert_one({
        "analysis_id": analysis_id,
        "user_id":     current_user["user_id"],
        "filename":    file.filename or "document",
        "file_type":   file_type,
        "status":      "processing",
        "created_at":  datetime.utcnow().isoformat(),
        "result":      None,
        "message":     None,
    })

    try:
        result = await analyze_with_gemini(content, file.content_type, file.filename or "document")
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "completed", "result": result, "completed_at": datetime.utcnow().isoformat()}},
        )
        return {"analysis_id": analysis_id, "status": "completed", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "failed", "message": str(e)}},
        )
        return {"analysis_id": analysis_id, "status": "failed", "message": str(e)}


@app.get("/api/analyses")
async def list_analyses(current_user=Depends(get_current_user)):
    cursor = analyses_col.find(
        {"user_id": current_user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(50)
    return await cursor.to_list(length=50)


@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, current_user=Depends(get_current_user)):
    doc = await analyses_col.find_one(
        {"analysis_id": analysis_id, "user_id": current_user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return doc


@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str, current_user=Depends(get_current_user)):
    result = await analyses_col.delete_one(
        {"analysis_id": analysis_id, "user_id": current_user["user_id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"deleted": True}


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=True)

