import os, uuid, logging, json, io, asyncio, httpx, re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
import motor.motor_asyncio
from jose import JWTError, jwt
from passlib.context import CryptContext
import pypdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET      = os.getenv("JWT_SECRET", "finsight-secret-key-2024")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 30
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")

executor = ThreadPoolExecutor(max_workers=4)
app = FastAPI(title="FinSight API v12")

# CORS
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

# DB
mongo_client  = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db            = mongo_client.finsight
users_col     = db.users
analyses_col  = db.analyses
companies_col = db.companies

# AUTH
pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def hash_pw(pw): return pwd_ctx.hash(pw)
def verify_pw(p, h): return pwd_ctx.verify(p, h)

def create_token(uid):
    exp = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": uid, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds: raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        uid = payload.get("sub")
        if not uid: raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Token expired or invalid — please sign in again")
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

# MODELS
class RegisterRequest(BaseModel):
    name: str; email: str; password: str

class LoginRequest(BaseModel):
    email: str; password: str

class AnalyzeFromURLRequest(BaseModel):
    pdf_url: str; filename: str; source: str

class PDFRequest(BaseModel):
    html: str

# HEADERS
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
NSE_HEADERS = {**BROWSER_HEADERS, "Referer": "https://www.nseindia.com/", "Origin": "https://www.nseindia.com", "Host": "www.nseindia.com"}
BSE_HEADERS = {**BROWSER_HEADERS, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}


# COMPANY MASTER SYNC
async def sync_nse_companies() -> int:
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    count = 0
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            await c.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            r = await c.get(url, headers=NSE_HEADERS)
            r.raise_for_status()
        lines = r.text.splitlines()
        if len(lines) < 2: return 0
        header = [h.strip().upper() for h in lines[0].split(",")]
        try:
            sym_idx  = header.index("SYMBOL")
            name_idx = header.index("NAME OF COMPANY")
            isin_idx = header.index("ISIN NUMBER") if "ISIN NUMBER" in header else -1
        except ValueError as e:
            logger.error(f"NSE CSV header mismatch: {e}"); return 0
        from pymongo import UpdateOne
        ops = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(sym_idx, name_idx): continue
            symbol = parts[sym_idx].strip().upper()
            name   = parts[name_idx].strip().title()
            isin   = parts[isin_idx].strip() if isin_idx != -1 and len(parts) > isin_idx else ""
            if not symbol or not name: continue
            ops.append(UpdateOne({"symbol": symbol},
                {"$set": {"symbol": symbol, "name": name, "isin": isin, "nse_listed": True, "active": True, "updated_at": datetime.utcnow().isoformat()}},
                upsert=True))
        for i in range(0, len(ops), 500):
            await companies_col.bulk_write(ops[i:i+500])
            count += len(ops[i:i+500])
        logger.info(f"NSE sync: {count} records")
    except Exception as e:
        logger.error(f"NSE sync failed: {e}")
    return count


async def sync_bse_companies() -> int:
    url = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
    count = 0
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.get(url, headers=BSE_HEADERS)
            r.raise_for_status()
            data = r.json()
        items = data if isinstance(data, list) else data.get("Table", data.get("data", []))
        logger.info(f"BSE returned {len(items)} scrips")
        from pymongo import UpdateOne
        ops = []
        for item in items:
            bse_code = str(item.get("SCRIP_CD") or item.get("scripCode") or item.get("ScripCode") or "").strip()
            nse_sym  = (item.get("NSE_SYMBOL") or item.get("nseSymbol") or item.get("scrip_id") or "").strip().upper()
            name     = (item.get("LONG_NAME") or item.get("longName") or item.get("scrip_name") or item.get("Issuer_Name") or "").strip().title()
            isin     = (item.get("ISIN_NO") or item.get("isinNumber") or item.get("ISIN") or "").strip()
            sector   = (item.get("INDUSTRY") or item.get("industry") or "").strip().title()
            if not bse_code or not name: continue
            if nse_sym:
                ops.append(UpdateOne({"symbol": nse_sym},
                    {"$set": {"bse_code": bse_code, "isin": isin, "sector": sector, "bse_listed": True, "active": True, "updated_at": datetime.utcnow().isoformat()}},
                    upsert=False))
                ops.append(UpdateOne({"symbol": nse_sym},
                    {"$setOnInsert": {"symbol": nse_sym, "name": name, "bse_code": bse_code, "isin": isin, "sector": sector, "nse_listed": False, "bse_listed": True, "active": True, "updated_at": datetime.utcnow().isoformat()}},
                    upsert=True))
            else:
                ops.append(UpdateOne({"bse_code": bse_code},
                    {"$set": {"symbol": f"BSE_{bse_code}", "name": name, "bse_code": bse_code, "isin": isin, "sector": sector, "nse_listed": False, "bse_listed": True, "active": True, "updated_at": datetime.utcnow().isoformat()}},
                    upsert=True))
            count += 1
        for i in range(0, len(ops), 500):
            await companies_col.bulk_write(ops[i:i+500])
        logger.info(f"BSE sync: {count} records")
    except Exception as e:
        logger.error(f"BSE sync failed: {e}")
    return count


async def ensure_indexes():
    await companies_col.create_index("symbol")
    await companies_col.create_index("bse_code")
    await companies_col.create_index("isin")
    await companies_col.create_index([("name", "text"), ("symbol", "text")])
    await analyses_col.create_index("analysis_id")
    await analyses_col.create_index("user_id")
    try: await users_col.create_index("email", unique=True)
    except: pass
    logger.info("Indexes ensured")


async def initial_sync():
    await ensure_indexes()
    count = await companies_col.count_documents({})
    if count == 0:
        logger.info("Company master empty — full sync starting...")
        n = await sync_nse_companies()
        b = await sync_bse_companies()
        logger.info(f"Initial sync done — NSE:{n}, BSE:{b}")
    else:
        latest = await companies_col.find_one({}, sort=[("updated_at", -1)])
        age_hrs = 999
        if latest:
            try: age_hrs = (datetime.utcnow() - datetime.fromisoformat(latest["updated_at"])).total_seconds() / 3600
            except: pass
        if age_hrs > 24:
            logger.info(f"Data {age_hrs:.0f}h old — refreshing in background")
            asyncio.create_task(sync_nse_companies())
            asyncio.create_task(sync_bse_companies())
        else:
            logger.info(f"Company master: {count:,} records, {age_hrs:.1f}h old")

async def _daily_sync_loop():
    while True:
        await asyncio.sleep(86400)
        await sync_nse_companies()
        await sync_bse_companies()

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(initial_sync())
    asyncio.create_task(_daily_sync_loop())


async def search_companies(query: str, limit: int = 15) -> List[dict]:
    q_upper = query.strip().upper()
    q_orig  = query.strip()
    results: List[dict] = []
    seen: set = set()

    def _add(doc, score):
        doc.pop("_id", None)
        key = doc.get("symbol") or doc.get("bse_code", "")
        if key and key not in seen:
            seen.add(key)
            results.append({**doc, "_score": score})

    doc = await companies_col.find_one({"symbol": q_upper})
    if doc: _add(doc, 100)
    async for doc in companies_col.find({"symbol": {"$regex": f"^{re.escape(q_upper)}", "$options": "i"}}, limit=10): _add(doc, 80)
    async for doc in companies_col.find({"name": {"$regex": f"^{re.escape(q_orig)}", "$options": "i"}}, limit=10): _add(doc, 60)
    if len(results) < limit:
        async for doc in companies_col.find({"name": {"$regex": re.escape(q_orig), "$options": "i"}}, limit=limit): _add(doc, 40)
    results.sort(key=lambda x: -x.pop("_score", 0))
    return results[:limit]


# FILING HELPERS
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


async def fetch_nse_filings(symbol: str) -> List[dict]:
    filings = []
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            await c.get("https://www.nseindia.com/", headers=NSE_HEADERS)

            # Endpoint 1: Annual reports
            r = await c.get(
                f"https://www.nseindia.com/api/annual-reports?symbol={symbol}&issuer={symbol}&type=annual-report",
                headers=NSE_HEADERS)
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    logger.warning(f"NSE annual-reports JSON decode failed for {symbol}")
                    data = {}
                items = data.get("data") or (data if isinstance(data, list) else [])
                for item in items[:10]:
                    pdf = (item.get("fileName") or item.get("pdfName") or item.get("attachment") or "").strip()
                    if not pdf: continue
                    if not pdf.startswith("http"):
                        pdf = f"https://www.nseindia.com/corporate-governance/annexure/{pdf}"
                    filings.append({"title": item.get("subject") or item.get("fileDesc") or "Annual Report",
                                    "date": item.get("dt") or item.get("sort_date") or "",
                                    "pdf_url": pdf, "type": "Annual Report", "source": "NSE", "symbol": symbol})
                if filings:
                    logger.info(f"NSE annual-reports: {len(filings)} for {symbol}")
                    return filings

            # Endpoint 2: Corporate announcements for annual reports + financial results
            for category in ["annual-report", "financial-results"]:
                r2 = await c.get(
                    f"https://www.nseindia.com/api/corporates-announcements?index=equities&symbol={symbol}&category={category}",
                    headers=NSE_HEADERS)
                if r2.status_code != 200: continue
                data2  = r2.json()
                items2 = data2.get("data", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
                for item in items2[:15]:
                    pdf   = (item.get("attchmntFile") or item.get("attachment") or "").strip()
                    title = item.get("subject") or item.get("desc") or "Filing"
                    if not pdf: continue
                    if not pdf.startswith("http"):
                        pdf = f"https://www.nseindia.com/{pdf.lstrip('/')}"
                    filings.append({"title": title, "date": item.get("an_dt") or item.get("dt") or "",
                                    "pdf_url": pdf, "type": _classify_filing(title), "source": "NSE", "symbol": symbol})
                if filings:
                    logger.info(f"NSE announcements ({category}): {len(filings)} for {symbol}")
                    return filings[:10]
    except Exception as e:
        logger.warning(f"NSE filings error for {symbol}: {e}")
    return filings


async def verify_pdf_url(c: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await c.head(url, headers=BSE_HEADERS, timeout=8)
        if r.status_code == 405:
            r = await c.get(url, headers={**BSE_HEADERS, "Range": "bytes=0-10"}, timeout=8)
        return r.status_code in (200, 206)
    except: return False


async def fetch_bse_filings(bse_code: str, symbol: str) -> List[dict]:
    if not bse_code: return []
    filings: List[dict] = []
    try:
        from datetime import date as _date
        to_dt   = _date.today().strftime("%Y%m%d")
        from_dt = (_date.today() - timedelta(days=1825)).strftime("%Y%m%d")  # 5 years

        def _bse_api(cat):
            return (f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
                    f"?pageno=1&strCat={cat}&strPrevDate={from_dt}&strScrip={bse_code}"
                    f"&strSearch=P&strToDate={to_dt}&strType=C")

        def _pdf_candidates(pdf_name):
            return [f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{pdf_name}",
                    f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{pdf_name}"]

        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            await c.get("https://www.bseindia.com/", headers=BSE_HEADERS)

            for cat, max_items, forced_type in [("Result", 20, None), ("Annual+Report", 8, "Annual Report")]:
                r = await c.get(_bse_api(cat), headers=BSE_HEADERS)
                if r.status_code != 200:
                    logger.warning(f"BSE API {cat} returned {r.status_code} for {bse_code}")
                    continue
                items = r.json().get("Table", [])
                logger.info(f"BSE {cat}: {len(items)} items for {bse_code}")

                for item in items[:max_items]:
                    pdf_name = item.get("ATTACHMENTNAME", "").strip()
                    if not pdf_name: continue
                    title = item.get("SUBJECT") or item.get("CATEGORYNAME") or "Financial Results"

                    # Verify URL — fall back to default if neither works (don't skip)
                    candidates = _pdf_candidates(pdf_name)
                    working_url = None
                    for candidate in candidates:
                        if await verify_pdf_url(c, candidate):
                            working_url = candidate
                            break
                    if not working_url:
                        working_url = candidates[0]  # Use AttachLive as default even if unverified
                        logger.warning(f"BSE PDF unverified, using default: {pdf_name}")

                    filings.append({"title": title, "date": item.get("NEWS_DT", ""),
                                    "pdf_url": working_url,
                                    "type": forced_type or _classify_filing(title),
                                    "source": "BSE", "symbol": symbol, "bse_code": bse_code})

        logger.info(f"BSE total: {len(filings)} filings for {bse_code}")
        return filings[:15]
    except Exception as e:
        logger.warning(f"BSE filings error for {bse_code}: {e}")
    return []


# PDF EXTRACTION
def extract_pdf_text(raw_bytes: bytes) -> str:
    """
    Entry point for PDF processing.
    Validates the PDF, checks it's not scanned, then extracts only financial pages.
    """
    try:
        reader    = pypdf.PdfReader(io.BytesIO(raw_bytes))
        num_pages = len(reader.pages)

        # Quick scan to check if PDF has any selectable text
        sample_text = ""
        for page in reader.pages[:10]:
            sample_text += page.extract_text() or ""
        if len(sample_text.strip()) < 300:
            raise ValueError(
                f"This PDF appears to be scanned/image-based — no selectable text found in first 10 pages. "
                f"Please download the digital/searchable version from BSE or NSE.")

        logger.info(f"PDF validated: {num_pages} pages, extracting financial sections...")
        return extract_financial_snippet(raw_bytes)

    except ValueError: raise
    except Exception as e:
        logger.error(f"PDF read error: {e}")
        raise ValueError(f"Could not read this PDF: {str(e)}")


# JSON REPAIR
def safe_parse_json(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON found. Preview: {raw[:200]}")
    depth, end, in_str, esc = 0, -1, False, False
    for i, ch in enumerate(raw[start:], start=start):
        if esc:         esc = False; continue
        if ch == "\\" and in_str: esc = True; continue
        if ch == '"':   in_str = not in_str; continue
        if in_str:      continue
        if ch == "{":   depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0: end = i + 1; break
    json_str = raw[start:end] if end != -1 else _repair_json(raw[start:])
    try: return json.loads(json_str)
    except json.JSONDecodeError: return json.loads(_repair_json(json_str))

def _repair_json(s: str) -> str:
    last_comma = s.rfind(",")
    if last_comma > len(s) // 2: s = s[:last_comma]
    d_b = d_br = 0
    in_str = esc = False
    for ch in s:
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"': in_str = not in_str; continue
        if in_str: continue
        if ch == "{": d_b += 1
        elif ch == "}": d_b -= 1
        elif ch == "[": d_br += 1
        elif ch == "]": d_br -= 1
    s = s.rstrip().rstrip(",")
    s += "]" * max(d_br, 0)
    s += "}" * max(d_b, 0)
    return s


# AI PROMPT

def extract_financial_snippet(raw_bytes: bytes, max_chars: int = 35000) -> str:
    """
    Page-score extraction: scores every page by how many financial keywords it contains.
    Pages with score >= 3 are core financial statement pages (Balance Sheet, P&L, Cash Flow).
    Always includes first 5 pages (Director Report / Financial Highlights).
    Works for ANY company PDF — no hardcoded patterns.
    """
    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    total  = len(reader.pages)

    KEYWORDS = [
        "total assets", "profit and loss", "statement of profit",
        "cash flow", "balance sheet", "total income", "borrowing",
        "finance cost", "total equity", "earnings per share",
        "debt to equity", "financial highlights", "key financial ratios",
        "total revenue", "gross income", "net profit", "ebitda",
        "total liabilities", "current assets", "current liabilities",
    ]

    core_pages = set(range(min(5, total)))  # first 5 pages always included
    for i, page in enumerate(reader.pages):
        t = (page.extract_text() or "").lower()
        score = sum(1 for kw in KEYWORDS if kw in t)
        if score >= 3:
            core_pages.add(i)

    logger.info(f"PDF: {total} pages, {len(core_pages)} financial pages selected: {sorted(core_pages)}")

    result = ""
    for i in sorted(core_pages):
        pt = reader.pages[i].extract_text() or ""
        if pt.strip():
            result += f"\n--- PAGE {i+1} ---\n{pt}\n"

    logger.info(f"Extracted {len(result):,} chars from financial pages")
    return result[:max_chars]


def build_prompt(text: str) -> str:
    # text here is already the financial-pages extract — pass it directly
    snippet = text[:35000]
    logger.info(f"Prompt snippet: {len(snippet)} chars")

    return f"""You are a Senior Equity Research Analyst, Credit Analyst, and Forensic Accounting Expert with 20+ years of experience.

Analyze the provided financial document and return ONLY a single valid JSON object. No markdown, no code fences, no explanation text before or after.

ABSOLUTE RULES:
1. Use ONLY real numbers extracted from the document. Do NOT invent numbers.
2. NEVER write "Not reported" if the data exists anywhere in the document — search carefully.
3. COMPUTE every possible ratio from available data. Examples:
   - Net Profit Margin = PAT / Total Income × 100
   - EBITDA = PBT + Depreciation + Finance Costs (if not stated directly)
   - EBITDA Margin = EBITDA / Total Income × 100
   - Debt to Equity = Total Debt (Debt Securities + Borrowings) / Total Equity
   - ROE = PAT / Total Equity × 100
   - ROA = PAT / Total Assets × 100
   - Interest Coverage = EBIT / Finance Costs
   - Current Ratio = Current Assets / Current Liabilities (if available)
4. For NBFCs and financial companies: Total Debt = Debt Securities + Borrowings (other than debt securities) + Subordinated Liabilities
5. NEVER write placeholder text like "val", "X%", "actual value", "actual %", or template labels.
6. Only write "Not reported" when the underlying raw numbers to compute a metric are completely absent — this should be RARE.
{{
  "company_name": "Full legal name from document",
  "statement_type": "Annual Report / Q1 Results / Q2 Results / Q3 Results / Q4 Results / Half-Year Results / Balance Sheet",
  "period": "e.g. FY2024-25 or Q3 FY2025",
  "currency": "INR Crores / USD Millions / etc",
  "health_score": 0,
  "health_label": "Excellent / Good / Fair / Poor / Critical",
  "health_score_breakdown": {{
    "total": 0,
    "components": [
      {{"category": "Profitability",     "weight": 20, "score": 0, "max": 20, "rating": "Strong/Average/Weak", "reasoning": "real numbers from doc"}},
      {{"category": "Growth",            "weight": 15, "score": 0, "max": 15, "rating": "Strong/Average/Weak", "reasoning": "real growth figures"}},
      {{"category": "Balance Sheet",     "weight": 15, "score": 0, "max": 15, "rating": "Strong/Average/Weak", "reasoning": "real debt/equity figures"}},
      {{"category": "Liquidity",         "weight": 10, "score": 0, "max": 10, "rating": "Strong/Average/Weak", "reasoning": "real current ratio/cash"}},
      {{"category": "Cash Flow",         "weight": 15, "score": 0, "max": 15, "rating": "Strong/Average/Weak", "reasoning": "real OCF vs PAT"}},
      {{"category": "Governance & Risk", "weight": 15, "score": 0, "max": 15, "rating": "Strong/Average/Weak", "reasoning": "fraud signals, mgmt quality"}},
      {{"category": "Industry Position", "weight": 10, "score": 0, "max": 10, "rating": "Strong/Average/Weak", "reasoning": "peer comparison"}}
    ]
  }},
  "executive_summary": "5-6 sentences: what company does, improved or deteriorated, financial strength, one-line investment view. Use REAL numbers.",
  "investor_verdict": "3-4 sentences for a beginner: interested or cautious and WHY. Real numbers only.",
  "explain_like_15": "5 lines using a small shop analogy. Fun and very simple. Real situation from the data.",
  "investment_label": "Strong Buy / Buy / Hold / Risky / Avoid",
  "key_metrics": [
    {{"label": "Revenue / Total Income",  "current": "REAL value", "previous": "REAL value", "change": "REAL % YoY", "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Net Profit / PAT",        "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "EBITDA",                  "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "EBITDA Margin",           "current": "REAL %",     "previous": "REAL %",     "change": "REAL bps",   "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Net Profit Margin",       "current": "REAL %",     "previous": "REAL %",     "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "EPS (Basic)",             "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Total Assets",            "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Total Debt",              "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Cash & Equivalents",      "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "ROE",                     "current": "REAL %",     "previous": "REAL %",     "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "ROCE",                    "current": "REAL %",     "previous": "REAL %",     "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Debt to Equity",          "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Interest Coverage",       "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Current Ratio",           "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}},
    {{"label": "Operating Cash Flow",     "current": "REAL value", "previous": "REAL value", "change": "REAL %",     "trend": "up/down/neutral", "comment": "simple explanation"}}
  ],
  "financial_performance": {{
    "revenue_analysis": "Real revenue growth explanation with exact numbers. Strong or weak? Why?",
    "profitability_analysis": "Real EBITDA/PAT/margin trend with exact numbers. Why did margins change?",
    "ratio_interpretation": [
      {{"ratio": "EBITDA Margin",     "value": "REAL %", "classification": "Strong/Average/Weak", "simple_explanation": "plain English"}},
      {{"ratio": "Net Profit Margin", "value": "REAL %", "classification": "Strong/Average/Weak", "simple_explanation": "plain English"}},
      {{"ratio": "ROE",               "value": "REAL %", "classification": "Strong/Average/Weak", "simple_explanation": "plain English"}},
      {{"ratio": "ROCE",              "value": "REAL %", "classification": "Strong/Average/Weak", "simple_explanation": "plain English"}}
    ]
  }},
  "profitability": {{
    "analysis": "3-4 sentences with real numbers, simple language",
    "gross_margin_current": "REAL % or Not reported", "gross_margin_previous": "REAL % or Not reported",
    "net_margin_current": "REAL %", "net_margin_previous": "REAL %",
    "ebitda_margin_current": "REAL %", "ebitda_margin_previous": "REAL %",
    "roe": "REAL % or Not reported", "roa": "REAL % or Not reported",
    "key_cost_drivers": ["Real cost driver 1 with number", "Real cost driver 2 with number"]
  }},
  "growth": {{
    "analysis": "3-4 sentences on growth quality and consistency, simple English",
    "revenue_growth_yoy": "REAL %", "profit_growth_yoy": "REAL %",
    "multi_year_trend": "Improving / Stable / Deteriorating",
    "multi_year_explanation": "2-5 year trend in simple words from available data",
    "volume_growth": "REAL % or Not reported",
    "guidance": "What management said about future growth or Not reported"
  }},
  "balance_sheet": {{
    "analysis": "2-3 sentences: overleveraged? comfortable repayment? Simple English.",
    "total_debt": "REAL value", "net_worth": "REAL value", "debt_to_equity": "REAL value",
    "interest_coverage": "REAL value or Not reported",
    "is_overleveraged": false,
    "debt_comfort_level": "Comfortable / Moderate / Stressed"
  }},
  "liquidity": {{
    "analysis": "2-3 sentences: can company run day-to-day operations smoothly?",
    "current_ratio": "REAL value", "quick_ratio": "REAL value or Not reported",
    "cash_position": "REAL value", "operating_cash_flow": "REAL value or Not reported",
    "free_cash_flow": "REAL value or Not reported",
    "day_to_day_assessment": "Smooth / Adequate / Tight"
  }},
  "debt": {{
    "analysis": "2-3 sentences with real numbers",
    "total_debt": "REAL value", "debt_to_equity": "REAL value",
    "interest_coverage": "REAL value or Not reported",
    "net_debt": "REAL value or Not reported",
    "debt_trend": "Decreasing / Increasing / Stable"
  }},
  "cash_flow_quality": {{
    "analysis": "Are profits real or accounting? Generating or burning cash? Real numbers.",
    "pat": "REAL value", "operating_cash_flow": "REAL value or Not reported",
    "cash_vs_profit_assessment": "Real Cash Profits / Accounting Profits / Cash Burn",
    "quality_rating": "High / Medium / Low"
  }},
  "peer_comparison": {{
    "industry": "Industry name",
    "classification": "Better than peers / At par / Worse than peers",
    "margin_comparison": "How margins compare to industry",
    "roe_comparison": "How ROE compares to industry norms",
    "debt_comparison": "How debt compares to industry norms",
    "summary": "2-3 sentences simple English"
  }},
  "fraud_risk": {{
    "overall_risk": "Low / Moderate / High",
    "signals_checked": [
      {{"signal": "Profit rising but cash flow not rising",      "found": false, "detail": "numbers-based explanation"}},
      {{"signal": "Rising receivables or working capital stress","found": false, "detail": "explanation"}},
      {{"signal": "High other income contribution",             "found": false, "detail": "explanation"}},
      {{"signal": "Frequent exceptional items",                 "found": false, "detail": "explanation"}},
      {{"signal": "Sudden margin spikes without explanation",   "found": false, "detail": "explanation"}},
      {{"signal": "Debt rising but profits not rising",         "found": false, "detail": "explanation"}}
    ],
    "reasoning": "Overall fraud risk explanation in simple English"
  }},
  "management_commentary": {{
    "overall_tone": "Positive / Cautious / Neutral / Concerned",
    "key_points": ["Real point 1 from doc", "Real point 2", "Real point 3", "Real point 4", "Real point 5"],
    "outlook_statement": "Real management outlook",
    "concerns_raised": ["Real concern 1", "Real concern 2"],
    "management_interpretation": "Simple: what do management decisions mean for investors?"
  }},
  "segments": [{{"name": "Real segment name", "revenue": "REAL value", "growth": "REAL %", "margin": "REAL % or Not reported", "comment": "real observation"}}],
  "highlights": ["Real strength 1 with numbers", "Real strength 2 with numbers", "Real strength 3 with numbers", "Real strength 4 with numbers", "Real strength 5 with numbers"],
  "risks": ["Real risk 1 with reasoning/numbers", "Real risk 2", "Real risk 3", "Real risk 4", "Real risk 5"],
  "future_outlook": {{
    "growth_potential": "Real growth potential from numbers + management",
    "key_triggers": ["Real trigger 1", "Real trigger 2", "Real trigger 3"],
    "key_risks": ["Real risk 1", "Real risk 2", "Real risk 3"],
    "summary": "2-3 sentences future direction, simple English"
  }},
  "what_to_watch": ["Real watch item 1 with context", "Real watch item 2", "Real watch item 3"]
}}

IMPORTANT: Replace ALL template labels above (like "REAL value", "REAL %") with actual data from the document.
Never output "REAL value", "REAL %", "val", "X%", or any placeholder. Write "Not reported" only if data is genuinely missing.

COMPUTE ALL RATIOS from the numbers found in the document. Show your calculations in the reasoning.

FINANCIAL DOCUMENT:
{snippet}"""


# AI RUNNERS
def _sync_gemini(text: str) -> dict:
    import google.generativeai as genai
    import time
    genai.configure(api_key=GEMINI_API_KEY)
    # Try gemini-2.0-flash first, fall back to gemini-1.5-flash if quota exceeded
    gemini_models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b"]
    last_err = None
    for model_name in gemini_models:
        for attempt in range(2):  # 2 attempts per model (handles transient 429)
            try:
                model = genai.GenerativeModel(model_name,
                    generation_config={"temperature": 0.1, "max_output_tokens": 8192})
                resp = model.generate_content(build_prompt(text))
                logger.info(f"Gemini {model_name} response: {len(resp.text)} chars")
                return safe_parse_json(resp.text)
            except Exception as e:
                err_str = str(e)
                if "429" in err_str and attempt == 0:
                    wait = 10
                    logger.warning(f"Gemini {model_name} 429 — retrying in {wait}s")
                    time.sleep(wait)
                    continue
                last_err = e
                logger.warning(f"Gemini {model_name} failed: {err_str[:100]}")
                break  # try next model
    raise Exception(f"All Gemini models failed. Last: {last_err}")

# Active Groq models as of Feb 2026 (mixtral/gemma2 decommissioned)
# With 8k snippet, even small models can handle the payload
GROQ_MODELS = [
    "llama-3.3-70b-versatile",   # 128k ctx, best quality
    "llama-3.1-70b-versatile",   # 128k ctx, fallback
    "llama3-70b-8192",           # 8k ctx, stable
    "llama3-8b-8192",            # 8k ctx, fastest - works fine with 8k snippet
    "llama-3.1-8b-instant",      # instant tier, very fast
]

def _sync_groq(text: str) -> dict:
    from groq import Groq
    gc = Groq(api_key=GROQ_API_KEY)
    last_error = None
    for model in GROQ_MODELS:
        try:
            resp = gc.chat.completions.create(model=model,
                messages=[{"role": "user", "content": build_prompt(text)}],
                temperature=0.1, max_tokens=8192)
            raw = resp.choices[0].message.content
            logger.info(f"Groq {model}: {len(raw)} chars")
            return safe_parse_json(raw)
        except Exception as ex:
            logger.warning(f"Groq {model} failed: {str(ex)[:120]}")
            last_error = ex
    raise Exception(f"All Groq models failed. Last: {last_error}")

def _sync_together(text: str) -> dict:
    key = os.getenv("TOGETHER_API_KEY", "")
    if not key: raise Exception("No TOGETHER_API_KEY")
    import httpx as _h
    resp = _h.post("https://api.together.xyz/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
              "messages": [{"role": "user", "content": build_prompt(text)}],
              "temperature": 0.1, "max_tokens": 8192}, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    logger.info(f"Together AI: {len(raw)} chars")
    return safe_parse_json(raw)

def _sync_openrouter(text: str) -> dict:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key: raise Exception("No OPENROUTER_API_KEY")
    import httpx as _h, time
    # Multiple free models on OpenRouter as fallbacks
    or_models = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "meta-llama/llama-3.1-70b-instruct:free",
        "google/gemma-3-27b-it:free",
        "mistralai/mistral-7b-instruct:free",
    ]
    last_err = None
    for model_name in or_models:
        for attempt in range(2):
            try:
                resp = _h.post("https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                             "HTTP-Referer": "https://finsight.app"},
                    json={"model": model_name,
                          "messages": [{"role": "user", "content": build_prompt(text)}],
                          "temperature": 0.1, "max_tokens": 8192}, timeout=90)
                if resp.status_code == 429:
                    if attempt == 0:
                        logger.warning(f"OpenRouter {model_name} 429 — retrying in 10s")
                        time.sleep(10); continue
                    raise Exception(f"OpenRouter 429 on {model_name}")
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                logger.info(f"OpenRouter {model_name}: {len(raw)} chars")
                return safe_parse_json(raw)
            except Exception as e:
                last_err = e
                logger.warning(f"OpenRouter {model_name} failed: {str(e)[:100]}")
                break
    raise Exception(f"All OpenRouter models failed. Last: {last_err}")

async def run_analysis(text: str) -> dict:
    loop   = asyncio.get_event_loop()
    errors: List[str] = []

    if GEMINI_API_KEY:
        try:
            result = await loop.run_in_executor(executor, _sync_gemini, text)
            logger.info("✓ Gemini succeeded"); return result
        except Exception as e:
            logger.warning(f"Gemini failed: {e}"); errors.append(f"Gemini: {str(e)[:100]}")

    if GROQ_API_KEY:
        try:
            result = await loop.run_in_executor(executor, _sync_groq, text)
            return result
        except Exception as e:
            logger.error(f"All Groq failed: {e}"); errors.append(f"Groq: {str(e)[:100]}")

    try:
        result = await loop.run_in_executor(executor, _sync_together, text)
        logger.info("✓ Together AI succeeded"); return result
    except Exception as e:
        logger.warning(f"Together failed: {e}"); errors.append(f"Together: {str(e)[:100]}")

    try:
        result = await loop.run_in_executor(executor, _sync_openrouter, text)
        logger.info("✓ OpenRouter succeeded"); return result
    except Exception as e:
        logger.warning(f"OpenRouter failed: {e}"); errors.append(f"OpenRouter: {str(e)[:100]}")

    raise Exception("All AI providers failed. " + " | ".join(errors))


# ROUTES
@app.get("/api/health")
async def health():
    company_count = await companies_col.count_documents({})
    return {"status": "ok", "time": datetime.utcnow().isoformat(),
            "gemini": bool(GEMINI_API_KEY), "groq": bool(GROQ_API_KEY),
            "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
            "companies_in_db": company_count}

@app.post("/api/admin/sync-companies")
async def trigger_sync():
    asyncio.create_task(sync_nse_companies())
    asyncio.create_task(sync_bse_companies())
    return {"status": "sync started in background"}

@app.get("/api/admin/sync-status")
async def sync_status():
    count  = await companies_col.count_documents({})
    latest = await companies_col.find_one({}, sort=[("updated_at", -1)])
    return {"total_companies": count, "last_updated": latest.get("updated_at") if latest else None}

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    if not req.name.strip() or not req.email.strip() or not req.password:
        raise HTTPException(400, "All fields required")
    if len(req.password) < 6: raise HTTPException(400, "Password must be at least 6 characters")
    email = req.email.strip().lower()
    if await users_col.find_one({"email": email}): raise HTTPException(400, "Email already registered — please sign in")
    uid = str(uuid.uuid4())
    await users_col.insert_one({"user_id": uid, "name": req.name.strip(), "email": email,
        "password": hash_pw(req.password), "created_at": datetime.utcnow().isoformat()})
    return {"token": create_token(uid), "user_id": uid, "name": req.name.strip(), "email": email}

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    if not req.email.strip() or not req.password: raise HTTPException(400, "Email and password required")
    email = req.email.strip().lower()
    user  = await users_col.find_one({"email": email})
    if not user: raise HTTPException(401, "No account with this email. Please register first.")
    if not verify_pw(req.password, user["password"]): raise HTTPException(401, "Incorrect password")
    return {"token": create_token(user["user_id"]), "user_id": user["user_id"], "name": user["name"], "email": user["email"]}

@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}

@app.get("/api/nse/search")
async def nse_search(q: str = ""):
    if not q.strip(): return {"results": [], "query": ""}
    results = await search_companies(q, limit=15)
    return {"results": results, "query": q, "total": len(results)}

@app.get("/api/nse/popular")
async def nse_popular():
    popular = ["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","SBIN",
               "BAJFINANCE","ZOMATO","LT","WIPRO","ADANIENT","TATAMOTORS","HINDUNILVR","ITC","AXISBANK"]
    results = []
    for sym in popular:
        doc = await companies_col.find_one({"symbol": sym})
        if doc: doc.pop("_id", None); results.append(doc)
    return {"results": results}

@app.get("/api/filings/{symbol}")
async def get_filings(symbol: str):
    symbol  = symbol.upper().strip()
    company = await companies_col.find_one({"symbol": symbol})
    if not company:
        raise HTTPException(404, f"Company '{symbol}' not found. Try /api/nse/search?q={symbol}")

    bse_code = company.get("bse_code", "")
    results  = await asyncio.gather(
        fetch_nse_filings(symbol),
        fetch_bse_filings(bse_code, symbol) if bse_code else asyncio.sleep(0),
        return_exceptions=True)
    nse_filings = results[0] if isinstance(results[0], list) else []
    bse_filings = results[1] if isinstance(results[1], list) else []

    all_filings = bse_filings + nse_filings
    seen: set = set()
    unique: List[dict] = []
    for f in all_filings:
        key = f["title"][:40].lower()
        if key not in seen: seen.add(key); unique.append(f)

    def _parse_date(d):
        for fmt in ["%d %b %Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%Y%m%d"]:
            try: return datetime.strptime((d or "").strip(), fmt)
            except: pass
        return datetime.min

    unique.sort(key=lambda x: _parse_date(x.get("date", "")), reverse=True)
    return {"symbol": symbol, "company": company.get("name", symbol), "sector": company.get("sector", ""),
            "isin": company.get("isin", ""), "bse_code": bse_code, "filings": unique[:15], "total": len(unique)}

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), user=Depends(get_optional_user)):
    content = await file.read()
    if not content: raise HTTPException(400, "Empty file")
    filename    = file.filename or "document.pdf"
    analysis_id = str(uuid.uuid4())
    user_id     = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"
    await analyses_col.insert_one({"analysis_id": analysis_id, "user_id": user_id, "is_guest": user is None,
        "filename": filename, "status": "processing", "created_at": datetime.utcnow().isoformat(), "result": None})
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(executor, extract_pdf_text, content) if filename.lower().endswith(".pdf") else f"Image: {filename}"
        result = await run_analysis(text)
        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "completed", "result": result}})
        return {"analysis_id": analysis_id, "status": "completed", "result": result}
    except Exception as e:
        msg = str(e); logger.error(f"analyze failed {analysis_id}: {msg}")
        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "failed", "message": msg}})
        return {"analysis_id": analysis_id, "status": "failed", "message": msg}

@app.post("/api/analyze-from-url")
async def analyze_from_url(req: AnalyzeFromURLRequest, user=Depends(get_optional_user)):
    analysis_id = str(uuid.uuid4())
    user_id     = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"
    await analyses_col.insert_one({"analysis_id": analysis_id, "user_id": user_id, "is_guest": user is None,
        "filename": req.filename, "source": req.source, "pdf_url": req.pdf_url,
        "status": "processing", "created_at": datetime.utcnow().isoformat(), "result": None})
    try:
        logger.info(f"Fetching PDF from {req.source}: {req.pdf_url}")
        headers = NSE_HEADERS if req.source == "nse" else BSE_HEADERS
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as c:
            if req.source == "nse": await c.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            elif req.source == "bse": await c.get("https://www.bseindia.com/", headers=BSE_HEADERS)
            r = await c.get(req.pdf_url, headers=headers)
        if r.status_code != 200:
            raise Exception(f"Could not fetch PDF — HTTP {r.status_code}. File may have moved or expired.")
        if "html" in r.headers.get("content-type", "").lower():
            raise Exception("Server returned HTML instead of PDF. Filing link may have expired.")
        logger.info(f"Downloaded {len(r.content):,} bytes from {req.source}")
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(executor, extract_pdf_text, r.content)
        result = await run_analysis(text)
        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "completed", "result": result}})
        logger.info(f"URL analysis complete: {analysis_id}")
        return {"analysis_id": analysis_id, "status": "completed", "result": result}
    except Exception as e:
        msg = str(e); logger.error(f"URL analysis failed {analysis_id}: {msg}")
        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "failed", "message": msg}})
        return {"analysis_id": analysis_id, "status": "failed", "message": msg}

@app.get("/api/public/analyses/{analysis_id}")
async def public_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id": analysis_id})
    if not doc or doc.get("status") != "completed": raise HTTPException(404, "Analysis not found")
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@app.get("/api/analyses")
async def list_analyses(user=Depends(get_current_user)):
    docs = []
    async for doc in analyses_col.find({"user_id": user["user_id"]}).sort("created_at", -1):
        doc.pop("_id", None); docs.append(doc)
    return docs

@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id": analysis_id})
    if not doc: raise HTTPException(404, "Analysis not found")
    doc.pop("_id", None); return doc

@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str, user=Depends(get_current_user)):
    r = await analyses_col.delete_one({"analysis_id": analysis_id, "user_id": user["user_id"]})
    if r.deleted_count == 0: raise HTTPException(404, "Not found")
    return {"deleted": True}

@app.post("/api/generate-pdf")
async def generate_pdf(req: PDFRequest):
    HTML2PDF_KEY = os.getenv("HTML2PDF_KEY", "pdliSG0Ajq3ghYvV3adX4OSZNtRLL8IMo0gK52WPIfY3lDwQoFwGfWaHfxWsjUcQ")
    html_content = req.html[:500_000] if len(req.html) > 500_000 else req.html
    last_error = None
    for attempt in range(1, 4):
        try:
            logger.info(f"PDF generation attempt {attempt}/3 — {len(html_content)} chars")
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post("https://api.html2pdf.app/v1/generate",
                    json={"html": html_content, "apiKey": HTML2PDF_KEY, "zoom": 1, "landscape": False,
                          "marginTop": 10, "marginBottom": 10, "marginLeft": 10, "marginRight": 10},
                    headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                logger.info(f"PDF generated on attempt {attempt} — {len(r.content):,} bytes")
                return Response(content=r.content, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=FinSight_Analysis.pdf"})
            last_error = f"html2pdf.app {r.status_code}: {r.text[:200]}"
            logger.warning(f"Attempt {attempt}: {last_error}")
        except httpx.TimeoutException:
            last_error = f"Attempt {attempt} timed out after 90s"; logger.warning(last_error)
        except Exception as e:
            last_error = str(e); logger.warning(f"Attempt {attempt} error: {last_error}")
        if attempt < 3: await asyncio.sleep(3)
    raise HTTPException(504, f"PDF generation failed after 3 attempts. {last_error}")