import os, uuid, logging, json, io, asyncio, httpx
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request, BackgroundTasks
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
import motor.motor_asyncio
from jose import JWTError, jwt
from passlib.context import CryptContext
import pypdf

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET      = os.getenv("JWT_SECRET", "finsight-secret-key-2024")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 30
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")

executor = ThreadPoolExecutor(max_workers=4)
app = FastAPI(title="FinSight API v10")

# ── CORS ─────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        r = Response()
        r.headers.update({
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS,PATCH",
            "Access-Control-Allow-Headers": "Authorization,Content-Type,Accept",
        })
        return r
    response = await call_next(request)
    response.headers.update({
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS,PATCH",
        "Access-Control-Allow-Headers": "Authorization,Content-Type,Accept",
    })
    return response

# ── DB ────────────────────────────────────────────────────────────────────────
client       = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db           = client.finsight
users_col    = db.users
analyses_col = db.analyses

# ── AUTH ──────────────────────────────────────────────────────────────────────
pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def hash_pw(pw):       return pwd_ctx.hash(pw)
def verify_pw(p, h):   return pwd_ctx.verify(p, h)
def create_token(uid):
    exp = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": uid, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds: raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        uid = payload.get("sub")
        if not uid: raise HTTPException(401, "Invalid token")
    except JWTError as e:
        raise HTTPException(401, f"Token expired or invalid — please sign in again")
    user = await users_col.find_one({"user_id": uid})
    if not user: raise HTTPException(401, "Account not found — please sign in again")
    return user

async def get_optional_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds: return None
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        uid = payload.get("sub")
        if not uid: return None
        return await users_col.find_one({"user_id": uid})
    except: return None

# ── MODELS ────────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str; email: str; password: str

class LoginRequest(BaseModel):
    email: str; password: str

class AnalyzeFromURLRequest(BaseModel):
    pdf_url: str
    filename: str
    source: str  # "nse" | "bse" | "screener"

# ── HTTP CLIENT HEADERS (mimic browser) ──────────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

NSE_HEADERS = {
    **BROWSER_HEADERS,
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
    "Host": "www.nseindia.com",
}

BSE_HEADERS = {
    **BROWSER_HEADERS,
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

# ── NSE FILING FETCHER ────────────────────────────────────────────────────────
async def fetch_nse_filings(symbol: str) -> List[dict]:
    """
    Fetch corporate announcements from NSE for a given symbol.
    Returns list of filing dicts with title, date, pdf_url, type.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # First hit the main page to get NSE cookies (required)
            await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            
            # Now fetch the actual announcements
            url = f"https://www.nseindia.com/api/annual-reports?symbol={symbol}&issuer={symbol}&type=annual-report"
            r = await client.get(url, headers=NSE_HEADERS)
            
            if r.status_code == 200:
                data = r.json()
                filings = []
                for item in (data.get("data") or data if isinstance(data, list) else []):
                    pdf = item.get("fileName") or item.get("pdfName") or item.get("attachment") or ""
                    if not pdf: continue
                    if not pdf.startswith("http"):
                        pdf = f"https://www.nseindia.com/corporate-governance/annexure/{pdf}"
                    filings.append({
                        "title": item.get("subject") or item.get("fileDesc") or "Annual Report",
                        "date": item.get("dt") or item.get("sort_date") or "",
                        "pdf_url": pdf,
                        "type": "Annual Report",
                        "source": "NSE",
                        "symbol": symbol,
                    })
                if filings:
                    return filings[:10]
            
            # Fallback: try announcements endpoint
            url2 = f"https://www.nseindia.com/api/corporates-announcements?index=equities&symbol={symbol}&category=annual-report"
            r2 = await client.get(url2, headers=NSE_HEADERS)
            if r2.status_code == 200:
                data2 = r2.json()
                filings = []
                items = data2.get("data", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
                for item in items[:20]:
                    pdf = item.get("attchmntFile") or item.get("attachment") or ""
                    title = item.get("subject") or item.get("desc") or "Filing"
                    if not pdf: continue
                    if not pdf.startswith("http"):
                        pdf = f"https://www.nseindia.com/{pdf.lstrip('/')}"
                    filings.append({
                        "title": title,
                        "date": item.get("an_dt") or item.get("dt") or "",
                        "pdf_url": pdf,
                        "type": _classify_filing(title),
                        "source": "NSE",
                        "symbol": symbol,
                    })
                if filings:
                    return filings[:10]
    except Exception as e:
        logger.warning(f"NSE fetch error for {symbol}: {e}")
    return []

async def fetch_bse_filings(bse_code: str, symbol: str) -> List[dict]:
    """Fetch annual reports and quarterly results from BSE."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # BSE announcements API
            from datetime import date
            to_date = date.today().strftime("%Y%m%d")
            from_date = (date.today() - timedelta(days=1460)).strftime("%Y%m%d")  # 4 years
            
            url = (
                f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
                f"?pageno=1&strCat=Result&strPrevDate={from_date}&strScrip={bse_code}"
                f"&strSearch=P&strToDate={to_date}&strType=C"
            )
            r = await client.get(url, headers=BSE_HEADERS)
            
            filings = []
            if r.status_code == 200:
                data = r.json()
                items = data.get("Table", [])
                for item in items[:15]:
                    pdf_name = item.get("ATTACHMENTNAME", "")
                    if not pdf_name: continue
                    pdf_url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{pdf_name}"
                    title = item.get("SUBJECT", item.get("CATEGORYNAME", "Financial Results"))
                    filings.append({
                        "title": title,
                        "date": item.get("NEWS_DT", ""),
                        "pdf_url": pdf_url,
                        "type": _classify_filing(title),
                        "source": "BSE",
                        "symbol": symbol,
                        "bse_code": bse_code,
                    })
            
            # Also fetch annual reports
            url2 = (
                f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
                f"?pageno=1&strCat=Annual+Report&strPrevDate={from_date}&strScrip={bse_code}"
                f"&strSearch=P&strToDate={to_date}&strType=C"
            )
            r2 = await client.get(url2, headers=BSE_HEADERS)
            if r2.status_code == 200:
                data2 = r2.json()
                for item in (data2.get("Table", []))[:5]:
                    pdf_name = item.get("ATTACHMENTNAME", "")
                    if not pdf_name: continue
                    pdf_url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{pdf_name}"
                    filings.append({
                        "title": item.get("SUBJECT", "Annual Report"),
                        "date": item.get("NEWS_DT", ""),
                        "pdf_url": pdf_url,
                        "type": "Annual Report",
                        "source": "BSE",
                        "symbol": symbol,
                        "bse_code": bse_code,
                    })
            
            return filings[:12]
    except Exception as e:
        logger.warning(f"BSE fetch error for {bse_code}: {e}")
    return []

def _classify_filing(title: str) -> str:
    t = title.lower()
    if "annual" in t: return "Annual Report"
    if "q1" in t or "first quarter" in t or "june" in t: return "Q1 Results"
    if "q2" in t or "second quarter" in t or "september" in t: return "Q2 Results"
    if "q3" in t or "third quarter" in t or "december" in t: return "Q3 Results"
    if "q4" in t or "fourth quarter" in t or "march" in t: return "Q4 Results"
    if "half" in t or "h1" in t or "h2" in t: return "Half-Year Results"
    if "result" in t or "financial" in t: return "Financial Results"
    return "Filing"

# ── PDF EXTRACTION ────────────────────────────────────────────────────────────
def extract_pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = [p.extract_text() or "" for p in reader.pages]
        text = "\n\n".join(p for p in pages if p.strip())
        logger.info(f"Extracted {len(text)} chars from {len(reader.pages)}-page PDF")
        return text
    except Exception as e:
        logger.error(f"PDF extraction: {e}")
        return ""

# ── AI PROMPT ─────────────────────────────────────────────────────────────────
def build_prompt(text: str) -> str:
    return f"""You are a world-class senior financial analyst (CFA, 20+ years).
Analyse this financial document and return ONLY valid JSON. No markdown, no code blocks, no explanation.

RULES: Use EXACT numbers from document. Score components must sum to health_score total. N/A only if genuinely missing.

{{
  "company_name": "Full legal company name",
  "statement_type": "Annual Report / Q1 Results / Q2 Results / Q3 Results / Q4 Results / Half-Year Results / Balance Sheet",
  "period": "e.g. Q3 FY2024 or FY2023-24",
  "currency": "INR Crores / USD Millions / etc",
  "health_score": 75,
  "health_label": "Excellent / Good / Fair / Poor / Critical",
  "health_score_breakdown": {{
    "total": 75,
    "components": [
      {{"category": "Profitability", "weight": 30, "score": 22, "max": 30, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers here"}},
      {{"category": "Revenue Growth", "weight": 25, "score": 18, "max": 25, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers here"}},
      {{"category": "Debt & Leverage", "weight": 20, "score": 14, "max": 20, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers here"}},
      {{"category": "Liquidity", "weight": 15, "score": 12, "max": 15, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers here"}},
      {{"category": "Management & Outlook", "weight": 10, "score": 9, "max": 10, "rating": "Strong/Moderate/Weak", "reasoning": "tone and guidance quality"}}
    ]
  }},
  "executive_summary": "5-6 comprehensive sentences",
  "investor_verdict": "3-4 sentences plain English for non-finance reader",
  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "val", "previous": "val", "change": "+X% YoY", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit / PAT", "current": "val", "previous": "val", "change": "+X%", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA", "current": "val", "previous": "val", "change": "+X%", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA Margin", "current": "X%", "previous": "X%", "change": "+X bps", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Gross Margin", "current": "X%", "previous": "X%", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit Margin", "current": "X%", "previous": "X%", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EPS (Basic)", "current": "val", "previous": "val", "change": "val", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Assets", "current": "val", "previous": "val", "change": "val", "trend": "neutral", "comment": "context"}},
    {{"label": "Total Debt", "current": "val", "previous": "val", "change": "val", "trend": "down", "comment": "context"}},
    {{"label": "Cash & Equivalents", "current": "val", "previous": "val", "change": "val", "trend": "up", "comment": "context"}},
    {{"label": "ROE", "current": "X%", "previous": "X%", "change": "val", "trend": "up", "comment": "context"}},
    {{"label": "ROCE", "current": "X%", "previous": "X%", "change": "val", "trend": "up", "comment": "context"}},
    {{"label": "Debt to Equity", "current": "val", "previous": "val", "change": "val", "trend": "down", "comment": "context"}},
    {{"label": "Interest Coverage", "current": "val", "previous": "val", "change": "val", "trend": "up", "comment": "context"}},
    {{"label": "Operating Cash Flow", "current": "val", "previous": "val", "change": "val", "trend": "up", "comment": "context"}}
  ],
  "profitability": {{
    "analysis": "3-4 sentences with exact numbers",
    "gross_margin_current": "X%", "gross_margin_previous": "X%",
    "net_margin_current": "X%", "net_margin_previous": "X%",
    "ebitda_margin_current": "X%", "ebitda_margin_previous": "X%",
    "roe": "X%", "roa": "X%",
    "key_cost_drivers": ["Item with number", "Item 2"]
  }},
  "growth": {{
    "analysis": "3-4 sentences", "revenue_growth_yoy": "X%", "profit_growth_yoy": "X%",
    "volume_growth": "X% or N/A", "guidance": "guidance text or N/A"
  }},
  "liquidity": {{
    "analysis": "2-3 sentences", "current_ratio": "val", "quick_ratio": "val",
    "cash_position": "val", "operating_cash_flow": "val", "free_cash_flow": "val"
  }},
  "debt": {{
    "analysis": "2-3 sentences", "total_debt": "val", "debt_to_equity": "val",
    "interest_coverage": "val", "net_debt": "val", "debt_trend": "Decreasing/Increasing/Stable"
  }},
  "management_commentary": {{
    "overall_tone": "Positive/Cautious/Neutral/Concerned",
    "key_points": ["Point 1","Point 2","Point 3","Point 4","Point 5"],
    "outlook_statement": "what management said",
    "concerns_raised": ["Concern 1","Concern 2"]
  }},
  "segments": [{{"name":"Segment","revenue":"val","growth":"X%","margin":"X%","comment":"observation"}}],
  "highlights": ["Strength 1 with numbers","Strength 2","Strength 3","Strength 4"],
  "risks": ["Risk 1 with context","Risk 2","Risk 3"],
  "what_to_watch": ["Item 1","Item 2","Item 3"]
}}

DOCUMENT:
{text[:14000]}"""

# ── AI RUNNERS ─────────────────────────────────────────────────────────────────
def _sync_gemini(text: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash", generation_config={"temperature":0.1,"max_output_tokens":4096})
    resp = model.generate_content(build_prompt(text))
    raw = resp.text.strip().replace("```json","").replace("```","").strip()
    s,e = raw.find('{'), raw.rfind('}')+1
    return json.loads(raw[s:e] if s!=-1 else raw)

def _sync_groq(text: str) -> dict:
    from groq import Groq
    gc = Groq(api_key=GROQ_API_KEY)
    resp = gc.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user","content":build_prompt(text)}], temperature=0.1, max_tokens=4096)
    raw = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
    s,e = raw.find('{'), raw.rfind('}')+1
    return json.loads(raw[s:e] if s!=-1 else raw)

async def run_analysis(text: str) -> dict:
    loop = asyncio.get_event_loop()
    errors = []
    if GEMINI_API_KEY:
        try:
            result = await loop.run_in_executor(executor, _sync_gemini, text)
            logger.info("✓ Gemini succeeded")
            return result
        except Exception as e:
            logger.warning(f"Gemini failed: {e}"); errors.append(f"Gemini: {str(e)[:80]}")
    if GROQ_API_KEY:
        try:
            result = await loop.run_in_executor(executor, _sync_groq, text)
            logger.info("✓ Groq succeeded")
            return result
        except Exception as e:
            logger.error(f"Groq failed: {e}"); errors.append(f"Groq: {str(e)[:80]}")
    raise Exception("AI analysis failed. " + (" | ".join(errors) if errors else "No API keys configured."))

# ── NSE COMPANY DATABASE ──────────────────────────────────────────────────────
# BSE codes mapped to NSE symbols for BSE API calls
BSE_CODES = {
    "RELIANCE":"500325","TCS":"532540","HDFCBANK":"500180","INFY":"500209","ICICIBANK":"532174",
    "HINDUNILVR":"500696","ITC":"500875","SBIN":"500112","BHARTIARTL":"532454","KOTAKBANK":"500247",
    "WIPRO":"507685","AXISBANK":"532215","LT":"500510","ASIANPAINT":"500820","HCLTECH":"532281",
    "MARUTI":"532500","SUNPHARMA":"524715","TITAN":"500114","BAJFINANCE":"500034","NESTLEIND":"500790",
    "TECHM":"532755","ULTRACEMCO":"532538","POWERGRID":"532898","NTPC":"532555","ONGC":"500312",
    "COALINDIA":"533278","ADANIENT":"512599","ADANIPORTS":"532921","BAJAJFINSV":"532978","INDUSINDBK":"532187",
    "TATASTEEL":"500470","HINDALCO":"500440","JSWSTEEL":"500228","TATAMOTORS":"500570","HEROMOTOCO":"500182",
    "BAJAJ-AUTO":"532977","M&M":"500520","EICHERMOT":"505200","DRREDDY":"500124","CIPLA":"500087",
    "DIVISLAB":"532488","APOLLOHOSP":"508869","GRASIM":"500300","BRITANNIA":"500825","DABUR":"500096",
    "MARICO":"531642","GODREJCP":"532424","PIDILITIND":"500331","HAVELLS":"517354","ZOMATO":"543320",
    "IRCTC":"542830","DMART":"540376","LICI":"543526","PAYTM":"543396","NYKAA":"543384",
    "SBILIFE":"540719","HDFCLIFE":"540777","BANKBARODA":"532134","PNB":"532461","YESBANK":"532648",
    "IDFCFIRSTB":"539437","FEDERALBNK":"500469","CANBK":"532483","UNIONBANK":"532477",
    "RECLTD":"532955","PFC":"532810","GAIL":"532155","IOC":"530965","BPCL":"500547",
    "VEDL":"500295","SAIL":"500113","NMDC":"526371","TATACHEM":"500770","LUPIN":"500257",
    "AUROPHARMA":"524804","BIOCON":"532523","TORNTPHARM":"500420",
}

NSE_COMPANIES = [
    {"symbol":"RELIANCE","name":"Reliance Industries Ltd","sector":"Energy"},
    {"symbol":"TCS","name":"Tata Consultancy Services Ltd","sector":"IT"},
    {"symbol":"HDFCBANK","name":"HDFC Bank Ltd","sector":"Banking"},
    {"symbol":"INFY","name":"Infosys Ltd","sector":"IT"},
    {"symbol":"ICICIBANK","name":"ICICI Bank Ltd","sector":"Banking"},
    {"symbol":"HINDUNILVR","name":"Hindustan Unilever Ltd","sector":"FMCG"},
    {"symbol":"ITC","name":"ITC Ltd","sector":"FMCG"},
    {"symbol":"SBIN","name":"State Bank of India","sector":"Banking"},
    {"symbol":"BHARTIARTL","name":"Bharti Airtel Ltd","sector":"Telecom"},
    {"symbol":"KOTAKBANK","name":"Kotak Mahindra Bank Ltd","sector":"Banking"},
    {"symbol":"WIPRO","name":"Wipro Ltd","sector":"IT"},
    {"symbol":"AXISBANK","name":"Axis Bank Ltd","sector":"Banking"},
    {"symbol":"LT","name":"Larsen & Toubro Ltd","sector":"Infrastructure"},
    {"symbol":"ASIANPAINT","name":"Asian Paints Ltd","sector":"Consumer"},
    {"symbol":"HCLTECH","name":"HCL Technologies Ltd","sector":"IT"},
    {"symbol":"MARUTI","name":"Maruti Suzuki India Ltd","sector":"Auto"},
    {"symbol":"SUNPHARMA","name":"Sun Pharmaceutical Industries Ltd","sector":"Pharma"},
    {"symbol":"TITAN","name":"Titan Company Ltd","sector":"Consumer"},
    {"symbol":"BAJFINANCE","name":"Bajaj Finance Ltd","sector":"Finance"},
    {"symbol":"NESTLEIND","name":"Nestle India Ltd","sector":"FMCG"},
    {"symbol":"TECHM","name":"Tech Mahindra Ltd","sector":"IT"},
    {"symbol":"ULTRACEMCO","name":"UltraTech Cement Ltd","sector":"Cement"},
    {"symbol":"POWERGRID","name":"Power Grid Corporation of India Ltd","sector":"Power"},
    {"symbol":"NTPC","name":"NTPC Ltd","sector":"Power"},
    {"symbol":"ONGC","name":"Oil and Natural Gas Corporation Ltd","sector":"Energy"},
    {"symbol":"COALINDIA","name":"Coal India Ltd","sector":"Energy"},
    {"symbol":"ADANIENT","name":"Adani Enterprises Ltd","sector":"Diversified"},
    {"symbol":"ADANIPORTS","name":"Adani Ports & Special Economic Zone Ltd","sector":"Logistics"},
    {"symbol":"BAJAJFINSV","name":"Bajaj Finserv Ltd","sector":"Finance"},
    {"symbol":"INDUSINDBK","name":"IndusInd Bank Ltd","sector":"Banking"},
    {"symbol":"TATASTEEL","name":"Tata Steel Ltd","sector":"Metals"},
    {"symbol":"HINDALCO","name":"Hindalco Industries Ltd","sector":"Metals"},
    {"symbol":"JSWSTEEL","name":"JSW Steel Ltd","sector":"Metals"},
    {"symbol":"TATAMOTORS","name":"Tata Motors Ltd","sector":"Auto"},
    {"symbol":"HEROMOTOCO","name":"Hero MotoCorp Ltd","sector":"Auto"},
    {"symbol":"BAJAJ-AUTO","name":"Bajaj Auto Ltd","sector":"Auto"},
    {"symbol":"M&M","name":"Mahindra & Mahindra Ltd","sector":"Auto"},
    {"symbol":"EICHERMOT","name":"Eicher Motors Ltd","sector":"Auto"},
    {"symbol":"DRREDDY","name":"Dr Reddy's Laboratories Ltd","sector":"Pharma"},
    {"symbol":"CIPLA","name":"Cipla Ltd","sector":"Pharma"},
    {"symbol":"DIVISLAB","name":"Divi's Laboratories Ltd","sector":"Pharma"},
    {"symbol":"APOLLOHOSP","name":"Apollo Hospitals Enterprise Ltd","sector":"Healthcare"},
    {"symbol":"GRASIM","name":"Grasim Industries Ltd","sector":"Diversified"},
    {"symbol":"BRITANNIA","name":"Britannia Industries Ltd","sector":"FMCG"},
    {"symbol":"DABUR","name":"Dabur India Ltd","sector":"FMCG"},
    {"symbol":"MARICO","name":"Marico Ltd","sector":"FMCG"},
    {"symbol":"GODREJCP","name":"Godrej Consumer Products Ltd","sector":"FMCG"},
    {"symbol":"HAVELLS","name":"Havells India Ltd","sector":"Electricals"},
    {"symbol":"ZOMATO","name":"Zomato Ltd","sector":"Fintech"},
    {"symbol":"IRCTC","name":"Indian Railway Catering and Tourism Corp","sector":"Services"},
    {"symbol":"DMART","name":"Avenue Supermarts Ltd (D-Mart)","sector":"Retail"},
    {"symbol":"LICI","name":"Life Insurance Corporation of India","sector":"Insurance"},
    {"symbol":"PAYTM","name":"One 97 Communications Ltd (Paytm)","sector":"Fintech"},
    {"symbol":"NYKAA","name":"FSN E-Commerce Ventures Ltd (Nykaa)","sector":"E-Commerce"},
    {"symbol":"SBILIFE","name":"SBI Life Insurance Company Ltd","sector":"Insurance"},
    {"symbol":"HDFCLIFE","name":"HDFC Life Insurance Company Ltd","sector":"Insurance"},
    {"symbol":"BANKBARODA","name":"Bank of Baroda","sector":"Banking"},
    {"symbol":"PNB","name":"Punjab National Bank","sector":"Banking"},
    {"symbol":"YESBANK","name":"Yes Bank Ltd","sector":"Banking"},
    {"symbol":"IDFCFIRSTB","name":"IDFC First Bank Ltd","sector":"Banking"},
    {"symbol":"FEDERALBNK","name":"The Federal Bank Ltd","sector":"Banking"},
    {"symbol":"CANBK","name":"Canara Bank","sector":"Banking"},
    {"symbol":"UNIONBANK","name":"Union Bank of India","sector":"Banking"},
    {"symbol":"RECLTD","name":"REC Ltd","sector":"Finance"},
    {"symbol":"PFC","name":"Power Finance Corporation Ltd","sector":"Finance"},
    {"symbol":"GAIL","name":"GAIL (India) Ltd","sector":"Energy"},
    {"symbol":"IOC","name":"Indian Oil Corporation Ltd","sector":"Energy"},
    {"symbol":"BPCL","name":"Bharat Petroleum Corporation Ltd","sector":"Energy"},
    {"symbol":"VEDL","name":"Vedanta Ltd","sector":"Metals"},
    {"symbol":"SAIL","name":"Steel Authority of India Ltd","sector":"Metals"},
    {"symbol":"NMDC","name":"NMDC Ltd","sector":"Metals"},
    {"symbol":"LUPIN","name":"Lupin Ltd","sector":"Pharma"},
    {"symbol":"AUROPHARMA","name":"Aurobindo Pharma Ltd","sector":"Pharma"},
    {"symbol":"BIOCON","name":"Biocon Ltd","sector":"Pharma"},
    {"symbol":"TORNTPHARM","name":"Torrent Pharmaceuticals Ltd","sector":"Pharma"},
    {"symbol":"MUTHOOTFIN","name":"Muthoot Finance Ltd","sector":"Finance"},
    {"symbol":"CHOLAFIN","name":"Cholamandalam Investment and Finance","sector":"Finance"},
    {"symbol":"PIDILITIND","name":"Pidilite Industries Ltd","sector":"Chemicals"},
    {"symbol":"BERGEPAINT","name":"Berger Paints India Ltd","sector":"Consumer"},
    {"symbol":"VOLTAS","name":"Voltas Ltd","sector":"Electricals"},
    {"symbol":"SIEMENS","name":"Siemens Ltd","sector":"Electricals"},
    {"symbol":"BOSCHLTD","name":"Bosch Ltd","sector":"Auto"},
    {"symbol":"JUBLFOOD","name":"Jubilant Foodworks Ltd","sector":"Retail"},
    {"symbol":"TRENT","name":"Trent Ltd","sector":"Retail"},
    {"symbol":"DELHIVERY","name":"Delhivery Ltd","sector":"Logistics"},
    {"symbol":"POLICYBZR","name":"PB Fintech Ltd (PolicyBazaar)","sector":"Fintech"},
    {"symbol":"ICICIGI","name":"ICICI Lombard General Insurance","sector":"Insurance"},
    {"symbol":"HPCL","name":"Hindustan Petroleum Corporation Ltd","sector":"Energy"},
    {"symbol":"NTPC","name":"NTPC Ltd","sector":"Power"},
    {"symbol":"IRFC","name":"Indian Railway Finance Corporation Ltd","sector":"Finance"},
    {"symbol":"NHPC","name":"NHPC Ltd","sector":"Power"},
    {"symbol":"SJVN","name":"SJVN Ltd","sector":"Power"},
    {"symbol":"TATACHEM","name":"Tata Chemicals Ltd","sector":"Chemicals"},
    {"symbol":"ABB","name":"ABB India Ltd","sector":"Electricals"},
]

# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status":"ok","time":datetime.utcnow().isoformat(),"gemini":bool(GEMINI_API_KEY),"groq":bool(GROQ_API_KEY)}

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    if not req.name.strip() or not req.email.strip() or not req.password:
        raise HTTPException(400, "All fields required")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    email = req.email.strip().lower()
    if await users_col.find_one({"email": email}):
        raise HTTPException(400, "Email already registered — please sign in")
    uid = str(uuid.uuid4())
    await users_col.insert_one({"user_id":uid,"name":req.name.strip(),"email":email,"password":hash_pw(req.password),"created_at":datetime.utcnow().isoformat()})
    return {"token":create_token(uid),"user_id":uid,"name":req.name.strip(),"email":email}

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    if not req.email.strip() or not req.password:
        raise HTTPException(400, "Email and password required")
    email = req.email.strip().lower()
    user = await users_col.find_one({"email": email})
    if not user: raise HTTPException(401, "No account with this email. Please register first.")
    if not verify_pw(req.password, user["password"]): raise HTTPException(401, "Incorrect password")
    return {"token":create_token(user["user_id"]),"user_id":user["user_id"],"name":user["name"],"email":user["email"]}

@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {"user_id":user["user_id"],"name":user["name"],"email":user["email"]}

# ── UPLOAD & ANALYZE ──────────────────────────────────────────────────────────
@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), user=Depends(get_optional_user)):
    content = await file.read()
    if not content: raise HTTPException(400, "Empty file")
    filename = file.filename or "document.pdf"
    is_pdf = filename.lower().endswith(".pdf")
    analysis_id = str(uuid.uuid4())
    user_id = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"

    await analyses_col.insert_one({"analysis_id":analysis_id,"user_id":user_id,"is_guest":user is None,"filename":filename,"status":"processing","created_at":datetime.utcnow().isoformat(),"result":None})
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(executor, extract_pdf_text, content) if is_pdf else f"Image: {filename}"
        if not text or len(text.strip()) < 30: text = f"[Minimal text extracted from {filename}]"
        result = await run_analysis(text)
        await analyses_col.update_one({"analysis_id":analysis_id},{"$set":{"status":"completed","result":result}})
        return {"analysis_id":analysis_id,"status":"completed","result":result}
    except Exception as e:
        await analyses_col.update_one({"analysis_id":analysis_id},{"$set":{"status":"failed","message":str(e)}})
        return {"analysis_id":analysis_id,"status":"failed","message":str(e)}

# ── ANALYZE FROM URL (one-tap from search results) ───────────────────────────
@app.post("/api/analyze-from-url")
async def analyze_from_url(req: AnalyzeFromURLRequest, user=Depends(get_optional_user)):
    """
    Fetch a PDF from NSE/BSE URL server-side and analyse it.
    This is the key endpoint that lets users one-tap analyze a filing without downloading.
    """
    analysis_id = str(uuid.uuid4())
    user_id = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"
    
    await analyses_col.insert_one({
        "analysis_id": analysis_id, "user_id": user_id,
        "is_guest": user is None, "filename": req.filename,
        "source": req.source, "pdf_url": req.pdf_url,
        "status": "processing", "created_at": datetime.utcnow().isoformat(), "result": None
    })
    
    try:
        logger.info(f"Fetching PDF: {req.pdf_url}")
        
        # Choose headers based on source
        headers = NSE_HEADERS if req.source == "nse" else BSE_HEADERS
        
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Hit homepage first to get session/cookies
            if req.source == "nse":
                await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            elif req.source == "bse":
                await client.get("https://www.bseindia.com/", headers=BSE_HEADERS)
            
            r = await client.get(req.pdf_url, headers=headers)
            
            if r.status_code != 200:
                raise Exception(f"Could not fetch PDF (HTTP {r.status_code}). The file may have moved.")
            
            content_type = r.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and len(r.content) < 1000:
                raise Exception("Response doesn't appear to be a valid PDF")
            
            pdf_bytes = r.content
        
        logger.info(f"Downloaded {len(pdf_bytes)} bytes from {req.source}")
        
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(executor, extract_pdf_text, pdf_bytes)
        
        if not text or len(text.strip()) < 50:
            raise Exception("Could not extract readable text from this PDF. It may be scanned/image-based.")
        
        result = await run_analysis(text)
        await analyses_col.update_one({"analysis_id":analysis_id},{"$set":{"status":"completed","result":result}})
        logger.info(f"✓ URL analysis done: {analysis_id}")
        return {"analysis_id":analysis_id,"status":"completed","result":result}
        
    except Exception as e:
        msg = str(e)
        logger.error(f"✗ URL analysis failed {analysis_id}: {msg}")
        await analyses_col.update_one({"analysis_id":analysis_id},{"$set":{"status":"failed","message":msg}})
        return {"analysis_id":analysis_id,"status":"failed","message":msg}

# ── NSE/BSE FILING FETCH ──────────────────────────────────────────────────────
@app.get("/api/filings/{symbol}")
async def get_filings(symbol: str):
    """
    Get list of real financial filings (PDFs) for a company from NSE and BSE.
    Returns filing list with pdf_url for one-tap analysis.
    """
    symbol = symbol.upper().strip()
    company = next((c for c in NSE_COMPANIES if c["symbol"] == symbol), None)
    if not company:
        raise HTTPException(404, f"Company {symbol} not found")
    
    bse_code = BSE_CODES.get(symbol, "")
    
    # Fetch from both NSE and BSE in parallel
    nse_task = fetch_nse_filings(symbol)
    bse_task = fetch_bse_filings(bse_code, symbol) if bse_code else asyncio.sleep(0)
    
    results = await asyncio.gather(nse_task, bse_task, return_exceptions=True)
    
    nse_filings = results[0] if isinstance(results[0], list) else []
    bse_filings = results[1] if isinstance(results[1], list) else []
    
    # Merge and sort by date (newest first)
    all_filings = bse_filings + nse_filings  # BSE usually more reliable
    
    # Deduplicate by similar title
    seen_titles = set()
    unique_filings = []
    for f in all_filings:
        key = f["title"][:40].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            unique_filings.append(f)
    
    # Sort by date descending
    def parse_date(d):
        try:
            for fmt in ["%d %b %Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y"]:
                try: return datetime.strptime(d.strip(), fmt)
                except: pass
        except: pass
        return datetime.min
    
    unique_filings.sort(key=lambda x: parse_date(x.get("date","") or ""), reverse=True)
    
    return {
        "symbol": symbol,
        "company": company["name"],
        "sector": company["sector"],
        "filings": unique_filings[:15],
        "bse_code": bse_code,
        "total": len(unique_filings),
    }

# ── NSE SEARCH ────────────────────────────────────────────────────────────────
@app.get("/api/nse/search")
async def nse_search(q: str = ""):
    if not q.strip(): return {"results":[],"query":""}
    q_lower = q.lower().strip()
    scored = []
    for c in NSE_COMPANIES:
        s = 0
        nl = c["name"].lower(); sl = c["symbol"].lower()
        if sl == q_lower: s=100
        elif nl == q_lower: s=90
        elif sl.startswith(q_lower): s=80
        elif q_lower in sl: s=70
        elif nl.startswith(q_lower): s=60
        elif q_lower in nl: s=50
        if s>0: scored.append({**c,"_score":s})
    scored.sort(key=lambda x:-x["_score"])
    return {"results":[{k:v for k,v in c.items() if k!="_score"} for c in scored[:12]],"query":q}

@app.get("/api/nse/popular")
async def nse_popular():
    syms = ["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","SBIN","BAJFINANCE","ZOMATO","LT","WIPRO","ADANIENT","TATAMOTORS"]
    return {"results":[c for c in NSE_COMPANIES if c["symbol"] in syms][:12]}

# ── RETRIEVE ──────────────────────────────────────────────────────────────────
@app.get("/api/public/analyses/{analysis_id}")
async def public_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id":analysis_id})
    if not doc or doc.get("status")!="completed": raise HTTPException(404,"Analysis not found")
    doc.pop("_id",None); doc.pop("user_id",None)
    return doc

@app.get("/api/analyses")
async def list_analyses(user=Depends(get_current_user)):
    docs=[]
    async for doc in analyses_col.find({"user_id":user["user_id"]}).sort("created_at",-1):
        doc.pop("_id",None); docs.append(doc)
    return docs

@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id":analysis_id})
    if not doc: raise HTTPException(404,"Analysis not found")
    doc.pop("_id",None)
    return doc

@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str, user=Depends(get_current_user)):
    r = await analyses_col.delete_one({"analysis_id":analysis_id,"user_id":user["user_id"]})
    if r.deleted_count==0: raise HTTPException(404,"Not found")
    return {"deleted":True}
