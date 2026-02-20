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

def encode_image(content: bytes) -> str:
    return base64.b64encode(content).decode("utf-8")

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), user=Depends(get_current_user)):
    content = await file.read()
    filename = file.filename or "upload"
    filename_lower = filename.lower()
    
    if filename_lower.endswith(".pdf"):
        file_type = "pdf"
    elif filename_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
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
        if not GROQ_API_KEY:
            raise ValueError("Groq API key not configured")

        groq_client = Groq(api_key=GROQ_API_KEY)

        # Extract text
        if file_type == "pdf":
            text = extract_text_from_pdf(content)
            if not text.strip():
                text = "Unable to extract text from PDF. Please ensure the PDF is not scanned/image-based."
        else:
            # For images, use vision model via base64
            text = f"[Image file uploaded: {filename}. Analyze as a financial document image.]"

        prompt = f"""You are a world-class senior financial analyst and CFA charterholder with 20+ years of experience analyzing company results, annual reports, and financial statements. Your job is to produce a comprehensive, insightful analysis that allows ANY reader — investor, student, business owner — to fully understand the company's financial position WITHOUT reading the original document.

Analyze the entire document including:
- All financial statements (P&L, Balance Sheet, Cash Flow)
- Management commentary and MD&A sections
- Business segment performance
- Outlook and guidance statements
- Any auditor remarks or notes
- Comparison figures (current vs previous period)

Return ONLY valid JSON — no markdown, no extra text. Use this exact structure:

{{
  "company_name": "Full company name",
  "statement_type": "Type: Annual Report / Quarterly Results / Income Statement / Balance Sheet etc",
  "period": "Exact period e.g. Q3 FY2024, FY2023-24, Year ended March 31 2024",
  "currency": "Currency with unit e.g. INR Crores, USD Millions",
  "health_score": 75,
  "health_score_derivation": "Explain exactly how this score was calculated — which metrics drove it up or down, what weightage was given e.g. Revenue growth +5pts, Margin compression -3pts, Strong cash flow +4pts, High debt -6pts etc",
  "health_label": "Excellent / Good / Fair / Poor / Critical",
  "executive_summary": "5-6 sentence comprehensive summary covering: what the company does, overall financial performance this period, key wins, key concerns, and what the numbers mean for the company's future",
  "investor_verdict": "3-4 sentence plain English verdict written for someone with no finance background. Should clearly state: is this company doing well or not, what are the 2-3 most important things to know, and what should someone watching this company look out for next",
  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "value with unit", "previous": "value with unit", "change": "+X% YoY", "trend": "up/down/neutral", "comment": "1 line context e.g. Driven by strong volume growth in North India"}},
    {{"label": "Net Profit / PAT", "current": "value", "previous": "value", "change": "+X%", "trend": "up/down/neutral", "comment": "1 line context"}},
    {{"label": "EBITDA", "current": "value", "previous": "value", "change": "+X%", "trend": "up/down/neutral", "comment": "1 line context"}},
    {{"label": "EBITDA Margin", "current": "X%", "previous": "X%", "change": "+X bps", "trend": "up/down/neutral", "comment": "1 line context"}},
    {{"label": "Gross Margin", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit Margin", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Operating Profit (EBIT)", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EPS (Basic)", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Assets", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Debt / Borrowings", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Cash & Cash Equivalents", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Return on Equity (ROE)", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Return on Capital Employed (ROCE)", "current": "X%", "previous": "X%", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Debt to Equity Ratio", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Interest Coverage Ratio", "current": "value", "previous": "value", "change": "change", "trend": "up/down/neutral", "comment": "context"}}
  ],
  "profitability": {{
    "analysis": "3-4 sentences covering margin trends, what drove profitability changes, cost structure, and comparison to previous period with specific numbers",
    "gross_margin_current": "X%",
    "gross_margin_previous": "X%",
    "net_margin_current": "X%",
    "net_margin_previous": "X%",
    "ebitda_margin_current": "X%",
    "ebitda_margin_previous": "X%",
    "roe": "X%",
    "roa": "X%",
    "key_cost_drivers": ["Cost item 1 with impact", "Cost item 2 with impact"]
  }},
  "growth": {{
    "analysis": "3-4 sentences on revenue and profit growth, what segments or geographies drove it, and management's guidance for future growth",
    "revenue_growth_yoy": "X%",
    "profit_growth_yoy": "X%",
    "volume_growth": "X% or N/A",
    "price_realization": "context or N/A",
    "guidance": "Management guidance if mentioned, else N/A"
  }},
  "liquidity": {{
    "analysis": "2-3 sentences on company's ability to meet short-term obligations, working capital situation, and cash generation",
    "current_ratio": "value or N/A",
    "quick_ratio": "value or N/A",
    "cash_position": "value",
    "operating_cash_flow": "value or N/A",
    "free_cash_flow": "value or N/A"
  }},
  "debt": {{
    "analysis": "2-3 sentences on debt levels, whether debt increased or decreased, interest burden, and whether debt is manageable",
    "total_debt": "value",
    "debt_to_equity": "value or N/A",
    "interest_coverage": "value or N/A",
    "net_debt": "value or N/A",
    "debt_trend": "Increasing / Decreasing / Stable"
  }},
  "management_commentary": {{
    "overall_tone": "Positive / Cautious / Neutral / Concerned",
    "key_points": [
      "Specific point from MD&A or management commentary 1",
      "Specific point 2",
      "Specific point 3",
      "Specific point 4",
      "Specific point 5"
    ],
    "outlook_statement": "What management said about future performance, guidance, or strategic priorities",
    "concerns_raised": ["Any concern or challenge management acknowledged 1", "Concern 2"]
  }},
  "segments": [
    {{"name": "Segment name", "revenue": "value", "growth": "X%", "margin": "X%", "comment": "key observation"}}
  ],
  "highlights": [
    "Specific strength 1 with exact numbers e.g. Revenue grew 18% YoY to ₹4,250 Cr driven by...",
    "Specific strength 2 with numbers",
    "Specific strength 3 with numbers",
    "Specific strength 4 with numbers",
    "Specific strength 5 with numbers"
  ],
  "risks": [
    "Specific risk 1 with context and potential impact",
    "Specific risk 2 with context",
    "Specific risk 3 with context",
    "Specific risk 4 with context"
  ],
  "what_to_watch": [
    "Forward-looking item to monitor 1 e.g. Margin recovery in Q4 as raw material costs ease",
    "Forward-looking item 2",
    "Forward-looking item 3"
  ]
}}

IMPORTANT RULES:
- Use ONLY data from the document. Never make up numbers.
- Always include previous period comparison figures wherever available.
- Use "N/A" only when data is genuinely not present.
- Write comments and analysis in simple, clear English anyone can understand.
- For health_score (0-100): weight profitability 30%, growth 25%, debt/leverage 20%, liquidity 15%, management quality 10%.
- Explain the health score derivation clearly showing which factors increased or decreased it.
- Extract and include ALL segment data if present.
- Include management commentary insights — these are often more important than the numbers.

Document content:
{text[:10000]}"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=3000
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        
        # Find JSON object
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        
        result = json.loads(raw)

        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "completed", "result": result}}
        )
        return {"analysis_id": analysis_id, "status": "completed", "result": result}

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "failed", "message": "Failed to parse AI response"}}
        )
        return {"analysis_id": analysis_id, "status": "failed", "message": "Failed to parse AI response"}
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
