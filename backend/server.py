import os
import uuid
import base64
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import Response, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pydantic import BaseModel
import motor.motor_asyncio
from jose import JWTError, jwt
from passlib.context import CryptContext
import google.generativeai as genai
import pypdf
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET      = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_MIN  = 60 * 24 * 7
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")

app = FastAPI(title="FinSight - Financial Analyzer", version="1.0.0")

@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, Origin, X-Requested-With"
        response.headers["Access-Control-Max-Age"] = "3600"
        return response
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, Origin, X-Requested-With"
    return response

client       = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db           = client.finsight
users_col    = db.users
analyses_col = db.analyses

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MIN)
    return jwt.encode({"sub": user_id, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await users_col.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    existing = await users_col.find_one({"email": req.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = str(uuid.uuid4())
    await users_col.insert_one({
        "user_id": user_id,
        "name": req.name,
        "email": req.email.lower(),
        "password": hash_password(req.password),
        "created_at": datetime.utcnow().isoformat()
    })
    token = create_token(user_id)
    return {"token": token, "user_id": user_id, "name": req.name, "email": req.email.lower()}

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = await users_col.find_one({"email": req.email.lower()})
    if not user or not verify_password(req.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["user_id"])
    return {"token": token, "user_id": user["user_id"], "name": user["name"], "email": user["email"]}

@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), user=Depends(get_current_user)):
    content = await file.read()
    filename = file.filename or "upload"
    file_type = "pdf" if filename.lower().endswith(".pdf") else "image"

    analysis_id = str(uuid.uuid4())
    doc = {
        "analysis_id": analysis_id,
        "user_id": user["user_id"],
        "filename": filename,
        "file_type": file_type,
        "status": "processing",
        "created_at": datetime.utcnow().isoformat(),
        "result": None
    }
    await analyses_col.insert_one(doc)

    try:
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API key not configured")

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash-001")

        if file_type == "pdf":
            try:
                reader = pypdf.PdfReader(io.BytesIO(content))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                if not text.strip():
                    raise ValueError("No text extracted")
                prompt = f"""Analyze this financial statement and return ONLY valid JSON:
{{"company_name": "string", "statement_type": "income_statement", "period": "string", "currency": "USD", "summary": "2-3 sentence summary", "health_score": 75, "health_label": "Good", "key_metrics": [{{"label": "Revenue", "value": "$1M", "change": "+10%", "trend": "up"}}], "highlights": ["point 1"], "risks": ["risk 1"]}}

Text: {text[:6000]}"""
                response = model.generate_content(prompt)
            except Exception:
                b64 = base64.b64encode(content).decode()
                prompt = 'Analyze this financial document and return ONLY valid JSON: {"company_name": "Unknown", "statement_type": "income_statement", "period": "Unknown", "currency": "USD", "summary": "Financial document analyzed.", "health_score": 70, "health_label": "Good", "key_metrics": [{"label": "N/A", "value": "N/A", "change": "N/A", "trend": "neutral"}], "highlights": ["Document processed"], "risks": ["Manual review recommended"]}'
                img_part = {"mime_type": "application/pdf", "data": b64}
                response = model.generate_content([prompt, img_part])
        else:
            b64 = base64.b64encode(content).decode()
            prompt = 'Analyze this financial statement image and return ONLY valid JSON: {"company_name": "string", "statement_type": "income_statement", "period": "string", "currency": "USD", "summary": "Brief summary", "health_score": 70, "health_label": "Good", "key_metrics": [{"label": "Key Metric", "value": "Value", "change": "N/A", "trend": "neutral"}], "highlights": ["Highlight 1"], "risks": ["Risk 1"]}'
            img_part = {"mime_type": file.content_type or "image/jpeg", "data": b64}
            response = model.generate_content([prompt, img_part])

        raw = response.text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "completed", "result": result}}
        )
        return {"analysis_id": analysis_id, "status": "completed", "result": result}

    except Exception as e:
        logger.error(f"Analysis error: {e}")
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "failed", "message": str(e)}}
        )
        return {"analysis_id": analysis_id, "status": "failed", "message": str(e)}

@app.get("/api/analyses")
async def get_analyses(user=Depends(get_current_user)):
    cursor = analyses_col.find({"user_id": user["user_id"]}).sort("created_at", -1)
    analyses = []
    async for doc in cursor:
        doc.pop("_id", None)
        analyses.append(doc)
    return analyses

@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, user=Depends(get_current_user)):
    doc = await analyses_col.find_one({"analysis_id": analysis_id, "user_id": user["user_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    doc.pop("_id", None)
    return doc

@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str, user=Depends(get_current_user)):
    result = await analyses_col.delete_one({"analysis_id": analysis_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"deleted": True}
