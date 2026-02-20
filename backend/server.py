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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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

def extract_text_from_pdf(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n".join(pages_text)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return ""

def build_prompt(text: str) -> str:
    return f"""You are a world-class senior financial analyst and CFA charterholder with 20+ years experience. Analyze this financial document comprehensively and return ONLY valid JSON — no markdown, no extra text.

CRITICAL: The health_score_breakdown must show SPECIFIC numbers and reasons from the actual document — not generic placeholders. Each factor must reference actual data found in the document.

Return this exact JSON structure:

{{
  "company_name": "Full company name",
  "statement_type": "Annual Report / Quarterly Results / Income Statement / Balance Sheet",
  "period": "Exact period e.g. Q3 FY2024, FY2023-24",
  "currency": "Currency with unit e.g. INR Crores, USD Millions",
  "health_score": 75,
  "health_label": "Excellent / Good / Fair / Poor / Critical",
  "health_score_breakdown": {{
    "total": 75,
    "components": [
      {{
        "category": "Profitability",
        "weight": 30,
        "score": 22,
        "max": 30,
        "rating": "Strong / Moderate / Weak",
        "reasoning": "Specific reasoning with actual numbers e.g. Net margin of 18.4% is strong, up from 16.2% last year. EBITDA margin at 24% indicates efficient cost management. ROE of 22% exceeds industry average of 15%."
      }},
      {{
        "category": "Revenue Growth",
        "weight": 25,
        "score": 18,
        "max": 25,
        "rating": "Strong / Moderate / Weak",
        "reasoning": "Specific reasoning with actual numbers e.g. Revenue grew 14.2% YoY to ₹4,250 Cr. Growth is broad-based across segments. However, Q3 growth of 8% shows slight deceleration from Q2's 16%."
      }},
      {{
        "category": "Debt & Leverage",
        "weight": 20,
        "score": 14,
        "max": 20,
        "rating": "Strong / Moderate / Weak",
        "reasoning": "Specific reasoning e.g. Debt-to-equity at 0.4x is conservative. Net debt reduced by ₹320 Cr this quarter. Interest coverage of 8.2x provides comfortable buffer. Company is actively deleveraging."
      }},
      {{
        "category": "Liquidity",
        "weight": 15,
        "score": 12,
        "max": 15,
        "rating": "Strong / Moderate / Weak",
        "reasoning": "Specific reasoning e.g. Current ratio of 2.1x is healthy. Cash and equivalents of ₹1,240 Cr is sufficient for 6 months operations. Strong operating cash flow of ₹680 Cr this year."
      }},
      {{
        "category": "Management & Outlook",
        "weight": 10,
        "score": 9,
        "max": 10,
        "rating": "Strong / Moderate / Weak",
        "reasoning": "Specific reasoning e.g. Management tone is confident with specific growth guidance of 15-18% for next year. New capacity expansion announced. Order book at all-time high of ₹8,500 Cr."
      }}
    ]
  }},
  "executive_summary": "5-6 sentence comprehensive summary: what company does, overall performance this period, key wins, key concerns, what numbers mean for future",
  "investor_verdict": "3-4 sentence plain English for non-finance person: is company doing well or not, 2-3 most important things to know, what to watch",
  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "value", "previous": "value", "change": "+X% YoY", "trend": "up/down/neutral", "comment": "one line context with actual driver"}},
    {{"label": "Net Profit / PAT", "current": "value", "previous": "value", "change": "+X%", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA", "current": "value", "previous": "value", "change": "+X%", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA Margin", "current": "X%", "previous": "X%", "change": "+X bps", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Gross Margin", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit Margin", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EPS (Basic)", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Assets", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Debt", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Cash & Equivalents", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "ROE", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "ROCE", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Debt to Equity", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Interest Coverage", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Operating Cash Flow", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}}
  ],
  "profitability": {{
    "analysis": "3-4 sentences on margin trends with specific numbers, cost structure, comparison to previous period",
    "gross_margin_current": "X%",
    "gross_margin_previous": "X%",
    "net_margin_current": "X%",
    "net_margin_previous": "X%",
    "ebitda_margin_current": "X%",
    "ebitda_margin_previous": "X%",
    "roe": "X%",
    "roa": "X%",
    "key_cost_drivers": ["Specific cost item 1 with actual impact e.g. Raw material costs fell 3% reducing COGS by ₹120 Cr", "Cost item 2"]
  }},
  "growth": {{
    "analysis": "3-4 sentences on revenue/profit growth with specific numbers, which segments/geographies drove it, deceleration or acceleration",
    "revenue_growth_yoy": "X%",
    "profit_growth_yoy": "X%",
    "volume_growth": "X% or N/A",
    "price_realization": "context or N/A",
    "guidance": "Exact guidance from management if mentioned"
  }},
  "liquidity": {{
    "analysis": "2-3 sentences on liquidity with specific numbers",
    "current_ratio": "value or N/A",
    "quick_ratio": "value or N/A",
    "cash_position": "value",
    "operating_cash_flow": "value or N/A",
    "free_cash_flow": "value or N/A"
  }},
  "debt": {{
    "analysis": "2-3 sentences on debt with specific numbers and trend",
    "total_debt": "value",
    "debt_to_equity": "value or N/A",
    "interest_coverage": "value or N/A",
    "net_debt": "value or N/A",
    "debt_trend": "Increasing / Decreasing / Stable"
  }},
  "management_commentary": {{
    "overall_tone": "Positive / Cautious / Neutral / Concerned",
    "key_points": ["Specific verbatim or paraphrased point from management 1", "Point 2", "Point 3", "Point 4", "Point 5"],
    "outlook_statement": "What management said about future performance",
    "concerns_raised": ["Specific concern management acknowledged 1", "Concern 2"]
  }},
  "segments": [
    {{"name": "Segment name", "revenue": "value", "growth": "X%", "margin": "X%", "comment": "key observation"}}
  ],
  "highlights": [
    "Specific strength with exact numbers e.g. Revenue grew 18% YoY to ₹4,250 Cr driven by North India expansion",
    "Strength 2 with numbers",
    "Strength 3",
    "Strength 4",
    "Strength 5"
  ],
  "risks": [
    "Specific risk with context and potential impact",
    "Risk 2",
    "Risk 3",
    "Risk 4"
  ],
  "what_to_watch": [
    "Forward looking item 1 e.g. Watch margin recovery in Q4 as management guided 50-100 bps improvement",
    "Item 2",
    "Item 3"
  ],
  "chart_data": {{
    "revenue_trend": [
      {{"period": "Q1", "value": 0}},
      {{"period": "Q2", "value": 0}},
      {{"period": "Q3", "value": 0}},
      {{"period": "Q4", "value": 0}}
    ],
    "margin_trend": [
      {{"period": "Q1", "gross": 0, "net": 0, "ebitda": 0}},
      {{"period": "Q2", "gross": 0, "net": 0, "ebitda": 0}},
      {{"period": "Q3", "gross": 0, "net": 0, "ebitda": 0}},
      {{"period": "Q4", "gross": 0, "net": 0, "ebitda": 0}}
    ]
  }}
}}

Rules:
- Use ONLY actual data from the document. Never invent numbers.
- health_score_breakdown reasoning MUST reference specific numbers from the document.
- Use "N/A" only when genuinely not present.
- For chart_data: fill in actual quarterly/yearly values if available, otherwise leave as 0.
- Include ALL segment data if present in document.
- Score components must add up to health_score total.

Document:
{text[:10000]}"""

async def analyze_with_groq(text: str) -> dict:
    groq_client = Groq(api_key=GROQ_API_KEY)
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": build_prompt(text)}],
        temperature=0.1,
        max_tokens=3500
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return json.loads(raw)

async def analyze_with_gemini(text: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(build_prompt(text))
    raw = response.text.strip().replace("```json", "").replace("```", "").strip()
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return json.loads(raw)

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
    filename_lower = filename.lower()

    if filename_lower.endswith(".pdf"):
        file_type = "pdf"
    elif filename_lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
        file_type = "image"
    else:
        file_type = "pdf"

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
        if file_type == "pdf":
            text = extract_text_from_pdf(content)
            if not text.strip():
                text = "Unable to extract text from this PDF."
        else:
            text = f"[Image file: {filename}. Analyze as financial document.]"

        result = None
        ai_used = None

        # Try Groq first
        if GROQ_API_KEY:
            try:
                logger.info("Attempting analysis with Groq...")
                result = await analyze_with_groq(text)
                ai_used = "groq"
                logger.info("Groq analysis successful")
            except Exception as e:
                logger.warning(f"Groq failed: {e}. Falling back to Gemini...")

        # Fallback to Gemini
        if result is None and GEMINI_API_KEY:
            try:
                logger.info("Attempting analysis with Gemini...")
                result = await analyze_with_gemini(text)
                ai_used = "gemini"
                logger.info("Gemini analysis successful")
            except Exception as e:
                logger.error(f"Gemini also failed: {e}")
                raise Exception("Both AI providers failed. Please try again later.")

        if result is None:
            raise Exception("No AI provider available. Please check API keys.")

        result["_ai_used"] = ai_used

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
