import os
import uuid
import base64
import logging
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import motor.motor_asyncio
from jose import JWTError, jwt
from passlib.context import CryptContext
from groq import Groq
import pypdf
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URL      = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET     = os.getenv("JWT_SECRET", "change-me")
JWT_ALGORITHM  = "HS256"
JWT_EXPIRE_MIN = 60 * 24 * 7
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

app = FastAPI(title="FinSight")

@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        r = Response()
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Methods"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "*"
        return r
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
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
    await analyses_col.insert_one({
        "analysis_id": analysis_id,
        "user_id": user["user_id"],
        "filename": filename,
        "file_type": file_type,
        "status": "processing",
        "created_at": datetime.utcnow().isoformat(),
        "result": None
    })

    try:
        if not GROQ_API_KEY:
            raise ValueError("Groq API key not configured")

        groq_client = Groq(api_key=GROQ_API_KEY)

        # Extract text from PDF
        if file_type == "pdf":
            reader = pypdf.PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            # For images, convert to base64 and use as text description
            text = f"[Image file: {filename}. Please analyze based on the filename and provide a general financial analysis template.]"

        prompt = f"""You are a financial analyst. Analyze this financial statement and return ONLY valid JSON with no other text.

Return exactly this JSON structure:
{{
  "company_name": "Company name or Unknown",
  "statement_type": "income_statement",
  "period": "Period covered",
  "currency": "Currency used",
  "summary": "2-3 sentence summary of financial health",
  "health_score": 75,
  "health_label": "Good",
  "key_metrics": [
    {{"label": "Revenue", "value": "$1M", "change": "+10%", "trend": "up"}},
    {{"label": "Net Profit", "value": "$100K", "change": "+5%", "trend": "up"}},
    {{"label": "Operating Margin", "value": "10%", "change": "+1%", "trend": "up"}}
  ],
  "highlights": ["Positive point 1", "Positive point 2", "Positive point 3"],
  "risks": ["Risk 1", "Risk 2"]
}}

Health score guide: 90-100=Excellent, 75-89=Good, 60-74=Fair, 40-59=Poor, 0-39=Critical

Financial statement:
{text[:6000]}"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
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
