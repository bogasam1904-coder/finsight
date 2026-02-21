import os, uuid, logging, json, io
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URL      = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET     = os.getenv("JWT_SECRET", "finsight-secret-2024")
JWT_ALGORITHM  = "HS256"
JWT_EXPIRE_MIN = 60 * 24 * 30   # 30 days — stay logged in
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

app = FastAPI(title="FinSight API")

@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        r = Response()
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        r.headers["Access-Control-Allow-Headers"] = "*"
        return r
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

client       = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db           = client.finsight
users_col    = db.users
analyses_col = db.analyses

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def hash_password(pw):       return pwd_ctx.hash(pw)
def verify_password(p, h):   return pwd_ctx.verify(p, h)
def create_token(user_id):
    exp = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MIN)
    return jwt.encode({"sub": user_id, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id: raise HTTPException(status_code=401, detail="Invalid token")
        user = await users_col.find_one({"user_id": user_id})
        if not user:    raise HTTPException(status_code=401, detail="User not found")
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

def extract_pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        logger.error(f"PDF error: {e}")
        return ""

def build_prompt(text: str) -> str:
    return f"""You are a world-class senior financial analyst (CFA, 20+ years experience).
Analyse this financial document thoroughly and return ONLY valid JSON with no markdown, no extra text.

CRITICAL: health_score_breakdown must use SPECIFIC numbers from the actual document.
Score components must add up exactly to health_score. Never invent numbers.

Return this exact JSON:
{{
  "company_name": "Full company name",
  "statement_type": "Annual Report / Quarterly Results / Balance Sheet / Income Statement",
  "period": "e.g. Q3 FY2024 or FY2023-24",
  "currency": "e.g. INR Crores or USD Millions",
  "health_score": 75,
  "health_label": "Excellent / Good / Fair / Poor / Critical",
  "health_score_breakdown": {{
    "total": 75,
    "components": [
      {{"category": "Profitability", "weight": 30, "score": 22, "max": 30, "rating": "Strong/Moderate/Weak", "reasoning": "Net margin X%, EBITDA Y%, ROE Z% — actual numbers from doc"}},
      {{"category": "Revenue Growth", "weight": 25, "score": 18, "max": 25, "rating": "Strong/Moderate/Weak", "reasoning": "Revenue grew X% YoY — actual figures"}},
      {{"category": "Debt & Leverage", "weight": 20, "score": 14, "max": 20, "rating": "Strong/Moderate/Weak", "reasoning": "D/E ratio X, interest coverage Y — actual figures"}},
      {{"category": "Liquidity", "weight": 15, "score": 12, "max": 15, "rating": "Strong/Moderate/Weak", "reasoning": "Current ratio X, cash Y — actual figures"}},
      {{"category": "Management & Outlook", "weight": 10, "score": 9, "max": 10, "rating": "Strong/Moderate/Weak", "reasoning": "Tone and guidance quality from doc"}}
    ]
  }},
  "executive_summary": "5-6 sentence comprehensive summary covering financials, operations, outlook",
  "investor_verdict": "3-4 sentences plain English for non-finance reader",
  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "val", "previous": "val", "change": "+X% YoY", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit / PAT", "current": "val", "previous": "val", "change": "+X%", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA", "current": "val", "previous": "val", "change": "+X%", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA Margin", "current": "X%", "previous": "X%", "change": "+X bps", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Gross Margin", "current": "X%", "previous": "X%", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit Margin", "current": "X%", "previous": "X%", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EPS (Basic)", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Assets", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Debt", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Cash & Equivalents", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "ROE", "current": "X%", "previous": "X%", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "ROCE", "current": "X%", "previous": "X%", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Debt to Equity", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Interest Coverage", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Operating Cash Flow", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}}
  ],
  "profitability": {{
    "analysis": "3-4 sentences with specific numbers",
    "gross_margin_current": "X%", "gross_margin_previous": "X%",
    "net_margin_current": "X%", "net_margin_previous": "X%",
    "ebitda_margin_current": "X%", "ebitda_margin_previous": "X%",
    "roe": "X%", "roa": "X%",
    "key_cost_drivers": ["Driver 1 with actual numbers", "Driver 2"]
  }},
  "growth": {{
    "analysis": "3-4 sentences with specific numbers",
    "revenue_growth_yoy": "X%", "profit_growth_yoy": "X%",
    "volume_growth": "X% or N/A", "price_realization": "context or N/A",
    "guidance": "Management guidance if any, else N/A"
  }},
  "liquidity": {{
    "analysis": "2-3 sentences",
    "current_ratio": "val or N/A", "quick_ratio": "val or N/A",
    "cash_position": "val", "operating_cash_flow": "val or N/A",
    "free_cash_flow": "val or N/A"
  }},
  "debt": {{
    "analysis": "2-3 sentences",
    "total_debt": "val", "debt_to_equity": "val or N/A",
    "interest_coverage": "val or N/A", "net_debt": "val or N/A",
    "debt_trend": "Increasing / Decreasing / Stable"
  }},
  "management_commentary": {{
    "overall_tone": "Positive / Cautious / Neutral / Concerned",
    "key_points": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"],
    "outlook_statement": "What management said about future",
    "concerns_raised": ["Concern 1", "Concern 2"]
  }},
  "segments": [
    {{"name": "Segment name", "revenue": "val", "growth": "X%", "margin": "X%", "comment": "key observation"}}
  ],
  "highlights": ["Strength 1 with numbers", "Strength 2", "Strength 3", "Strength 4", "Strength 5"],
  "risks": ["Risk 1 with context", "Risk 2", "Risk 3", "Risk 4"],
  "what_to_watch": ["Forward looking item 1", "Item 2", "Item 3"]
}}

Document:
{text[:12000]}"""

async def analyze_with_groq(text: str) -> dict:
    gc = Groq(api_key=GROQ_API_KEY)
    resp = gc.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": build_prompt(text)}],
        temperature=0.1, max_tokens=4000
    )
    raw = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
    s, e = raw.find('{'), raw.rfind('}') + 1
    return json.loads(raw[s:e] if s != -1 else raw)

async def analyze_with_gemini(text: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    resp = genai.GenerativeModel("gemini-2.0-flash").generate_content(build_prompt(text))
    raw = resp.text.strip().replace("```json","").replace("```","").strip()
    s, e = raw.find('{'), raw.rfind('}') + 1
    return json.loads(raw[s:e] if s != -1 else raw)

# ── ROUTES ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health(): return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    if await users_col.find_one({"email": req.email.lower()}):
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    await users_col.insert_one({
        "user_id": uid, "name": req.name,
        "email": req.email.lower(), "password": hash_password(req.password),
        "created_at": datetime.utcnow().isoformat()
    })
    return {"token": create_token(uid), "user_id": uid, "name": req.name, "email": req.email.lower()}

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = await users_col.find_one({"email": req.email.lower()})
    if not user or not verify_password(req.password, user["password"]):
        raise HTTPException(401, "Invalid email or password")
    return {"token": create_token(user["user_id"]), "user_id": user["user_id"], "name": user["name"], "email": user["email"]}

@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), user=Depends(get_current_user)):
    content = await file.read()
    filename = file.filename or "upload"
    is_pdf = filename.lower().endswith(".pdf")
    analysis_id = str(uuid.uuid4())

    await analyses_col.insert_one({
        "analysis_id": analysis_id, "user_id": user["user_id"],
        "filename": filename, "status": "processing",
        "created_at": datetime.utcnow().isoformat(), "result": None
    })

    try:
        text = extract_pdf_text(content) if is_pdf else f"Image: {filename}"
        if not text.strip(): text = "Could not extract text."

        result = None
        if GROQ_API_KEY:
            try: result = await analyze_with_groq(text)
            except Exception as e: logger.warning(f"Groq failed: {e}")
        if result is None and GEMINI_API_KEY:
            try: result = await analyze_with_gemini(text)
            except Exception as e: logger.error(f"Gemini failed: {e}")
        if result is None: raise Exception("All AI providers failed")

        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "completed", "result": result}})
        return {"analysis_id": analysis_id, "status": "completed", "result": result}
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "failed", "message": str(e)}})
        return {"analysis_id": analysis_id, "status": "failed", "message": str(e)}

# PUBLIC — no auth, anyone with link can view
@app.get("/api/public/analyses/{analysis_id}")
async def get_public_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id": analysis_id})
    if not doc or doc.get("status") != "completed":
        raise HTTPException(404, "Analysis not found")
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc

@app.get("/api/analyses")
async def list_analyses(user=Depends(get_current_user)):
    docs = []
    async for doc in analyses_col.find({"user_id": user["user_id"]}).sort("created_at", -1):
        doc.pop("_id", None)
        docs.append(doc)
    return docs

@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, user=Depends(get_current_user)):
    doc = await analyses_col.find_one({"analysis_id": analysis_id, "user_id": user["user_id"]})
    if not doc: raise HTTPException(404, "Not found")
    doc.pop("_id", None)
    return doc

@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str, user=Depends(get_current_user)):
    r = await analyses_col.delete_one({"analysis_id": analysis_id, "user_id": user["user_id"]})
    if r.deleted_count == 0: raise HTTPException(404, "Not found")
    return {"deleted": True}
