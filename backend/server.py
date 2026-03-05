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
    snippet = text[:50000]
    logger.info(f"Prompt snippet: {len(snippet)} chars")

    return f"""You are FinSight, an elite AI financial analyst combining 25+ years of equity research experience with the rigor of a Goldman Sachs analyst and the clarity of a seasoned investor communicator. You specialize in Indian listed companies across all sectors.

Analyze the provided financial document and return ONLY a single valid JSON object. No markdown, no code fences, no preamble, no trailing text.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE PHILOSOPHY — NON-NEGOTIABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. NEVER just describe numbers. Always EXPLAIN what they mean and WHY they matter to an investor.
2. ALWAYS contextualize metrics against the company's specific business model and sector dynamics.
3. Surface non-obvious risks and hidden signals that a casual reader would completely miss.
4. Be direct and specific. Never use vague language like "may", "could potentially", or "might consider".
5. Write as if a serious investor's capital depends on this analysis being accurate and insightful.
6. Flag concerns EVEN when the overall picture is positive. Intellectual honesty builds trust.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL EXTRACTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. SEARCH THE ENTIRE DOCUMENT for each metric before saying "Not reported"
2. Look for alternate names:
   - Total Assets = "Total Assets" OR "Assets" OR balance sheet total
   - Total Debt = "Total Borrowings" OR "Debt Securities" OR "Borrowings" OR "Loans"
   - Operating Cash Flow = "Cash from Operating Activities" OR "Net Cash from Operations"
   - Interest Coverage = calculate from "Finance Costs" and "EBIT" or "EBITDA"
3. For NBFCs: Total Debt = Debt Securities + Borrowings + Subordinated Liabilities
4. For Defense/PSU companies: Order book, government contracts, and advances from customers are critical
5. COMPUTE all ratios even if not explicitly stated:
   - ROE = (Net Profit / Total Equity) × 100
   - ROA = (Net Profit / Total Assets) × 100
   - Debt to Equity = Total Debt / Total Equity
   - Interest Coverage = EBIT / Finance Costs
   - Current Ratio = Current Assets / Current Liabilities
   - Free Cash Flow = Operating Cash Flow - Capex
6. Only say "Not reported" if underlying numbers are COMPLETELY ABSENT after thorough search

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORING CALIBRATION — STRICT ENFORCEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROFITABILITY (0-20):
- 18-20 = Strong  (ROE >20%, Net Margin >15%, consistent profitability)
- 12-17 = Average (ROE 12-20%, Net Margin 8-15%, stable profits)
- 0-11  = Weak    (ROE <12%, Net Margin <8%, declining profits)

GROWTH (0-15):
- 13-15 = Strong  (Revenue growth >20% YoY AND Profit growth >25%)
- 9-12  = Average (Revenue growth 10-20%, Profit growth 10-25%)
- 0-8   = Weak    (Revenue growth <10% OR Profit growth <10%)

BALANCE SHEET (0-15):
- 13-15 = Strong  (D/E <0.5, strong equity base, low debt)
- 9-12  = Average (D/E 0.5–1.5, moderate leverage)
- 0-8   = Weak    (D/E >1.5, high debt burden)

LIQUIDITY (0-10):
- 9-10 = Strong   (Current Ratio >1.5, strong cash position)
- 6-8  = Average  (Current Ratio 1.0–1.5, adequate cash)
- 0-5  = Weak     (Current Ratio <1.0, cash concerns)

CASH FLOW (0-15):
- 13-15 = Strong  (OCF > Net Profit, consistent generation)
- 9-12  = Average (OCF ≈ Net Profit, stable)
- 0-8   = Weak    (OCF < Net Profit or negative)

GOVERNANCE & RISK (0-15):
- 13-15 = Strong  (No red flags, AAA/AA+ rating, clean audit, low promoter pledge)
- 9-12  = Average (Minor concerns, good rating, no major flags)
- 0-8   = Weak    (Auditor qualifications, governance issues, high pledging)

INDUSTRY POSITION (0-10):
- 9-10 = Strong   (Market leader, durable moat, pricing power)
- 6-8  = Average  (At par with peers, no significant moat)
- 0-5  = Weak     (Below peer average, losing market share)

RATING MUST MATCH SCORE:
- Score ≥80% of max = "Strong" | Score 60-79% = "Average" | Score <60% = "Weak"
- If score is 12/15 → rating MUST be "Average" (NOT "Weak")
- If score is 16/20 → rating MUST be "Strong" (NOT "Average")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON OUTPUT SCHEMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "company_name": "Full legal name from document",
  "statement_type": "Annual Report / Half-Year Results / Quarterly Results",
  "period": "e.g. H1 FY2025-26 or Q2 FY2025",
  "currency": "INR Lakhs / INR Crores / USD Millions",
  "health_score": 0,
  "health_label": "Excellent (80-100) / Good (60-79) / Fair (40-59) / Poor (20-39) / Critical (0-19)",

  "health_score_breakdown": {{
    "total": 0,
    "components": [
      {{
        "category": "Profitability",
        "weight": 20,
        "score": 0,
        "max": 20,
        "rating": "Strong / Average / Weak — MUST match score using calibration",
        "reasoning": "ROE X%, Net Margin Y%, trend direction. Therefore [rating] because..."
      }},
      {{
        "category": "Growth",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "Revenue grew X% (volume-led or price-led?), Profit grew Y%. Gap explanation."
      }},
      {{
        "category": "Balance Sheet",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "D/E ratio X, Total Debt Y, asset quality assessment."
      }},
      {{
        "category": "Liquidity",
        "weight": 10,
        "score": 0,
        "max": 10,
        "rating": "Strong / Average / Weak",
        "reasoning": "Current Ratio X, Cash Y, working capital assessment."
      }},
      {{
        "category": "Cash Flow",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "OCF X vs PAT Y. Is profit backed by real cash? Why or why not?"
      }},
      {{
        "category": "Governance & Risk",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "Credit rating, auditor stance, promoter pledge %, related party concerns, red flags."
      }},
      {{
        "category": "Industry Position",
        "weight": 10,
        "score": 0,
        "max": 10,
        "rating": "Strong / Average / Weak",
        "reasoning": "Market rank vs named peers, moat source, pricing power, order pipeline."
      }}
    ]
  }},

  "executive_summary": "5-6 sentences. Lead with the most important story of the period. Use real numbers. Explain what drove performance, what the key risk is, and what investors must watch.",

  "headline": "One punchy, memorable sentence (max 15 words) that captures the essence of this result. Make it quotable.",

  "investment_label": "Strong Buy / Buy / Hold / Reduce / Avoid",

  "investor_verdict": "3-4 sentences. Direct recommendation with specific reasoning. Include what would change the view. Write as a senior analyst speaking to an institutional client.",

  "for_long_term_investors": "2-3 sentences specifically addressing long-term compounding potential, moat durability, and risk of permanent capital loss.",

  "for_short_term_traders": "2-3 sentences on near-term catalysts, technical setup context, and key triggers for the next quarter.",

  "bottom_line": "One single memorable sentence that is the most important thing any investor must know about this company right now. Make it unforgettable.",

  "explain_like_15": "Explain this company's financial health using a simple small shop analogy. 5 lines. No jargon. A 15-year-old must understand exactly how the business is doing and why.",

  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "ACTUAL number", "previous": "ACTUAL number", "change": "ACTUAL %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "What drove this? Volume or price? Organic or inorganic?"}},
    {{"label": "Net Profit / PAT", "current": "ACTUAL number", "previous": "ACTUAL number", "change": "ACTUAL %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Is profit growing faster or slower than revenue? Why?"}},
    {{"label": "EBITDA", "current": "Calculate or extract", "previous": "ACTUAL", "change": "ACTUAL %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Operating leverage story"}},
    {{"label": "EBITDA Margin", "current": "Calculate %", "previous": "ACTUAL %", "change": "bps", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Expanding or compressing? Key cost driver?"}},
    {{"label": "Net Profit Margin", "current": "Calculate %", "previous": "ACTUAL %", "change": "bps", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Divergence from EBITDA margin signals tax/interest dynamics"}},
    {{"label": "EPS (Basic)", "current": "ACTUAL", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Per-share value creation"}},
    {{"label": "Total Assets", "current": "SEARCH thoroughly", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Asset growth vs revenue growth — are assets being sweat efficiently?"}},
    {{"label": "Total Debt", "current": "Borrowings + Debt Securities", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Debt trajectory and its purpose"}},
    {{"label": "Cash & Equivalents", "current": "ACTUAL", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Cash burn or accumulation? Why?"}},
    {{"label": "ROE", "current": "Calculate PAT/Equity", "previous": "ACTUAL", "change": "bps", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Is equity being deployed effectively? DuPont breakdown if possible."}},
    {{"label": "ROCE", "current": "Calculate if available", "previous": "ACTUAL", "change": "bps", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Capital allocation quality"}},
    {{"label": "Debt to Equity", "current": "CALCULATE", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Leverage comfort level"}},
    {{"label": "Interest Coverage", "current": "CALCULATE EBIT/Finance Costs", "previous": "ACTUAL", "change": "x", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Debt servicing safety margin"}},
    {{"label": "Current Ratio", "current": "Calculate CA/CL", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Short-term financial health"}},
    {{"label": "Operating Cash Flow", "current": "EXTRACT from Cash Flow Statement", "previous": "ACTUAL", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Is profit real? OCF vs PAT gap explanation"}},
    {{"label": "Free Cash Flow", "current": "OCF minus Capex", "previous": "Calculate", "change": "%", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Cash available for dividends, buybacks, or growth after sustaining the business"}}
  ],

  "segment_analysis": {{
    "available": true,
    "segments": [
      {{
        "name": "Segment name",
        "revenue": "ACTUAL",
        "revenue_share": "% of total",
        "growth": "YoY %",
        "margin": "If available",
        "insight": "What is driving or dragging this segment? Is this the growth engine or the drag?"
      }}
    ],
    "key_takeaway": "Which segment is the real value driver? Which is the hidden risk?"
  }},

  "cash_flow_deep_dive": {{
    "operating_cf": "ACTUAL",
    "investing_cf": "ACTUAL",
    "financing_cf": "ACTUAL",
    "free_cash_flow": "OCF - Capex",
    "capex": "ACTUAL if available",
    "cash_conversion_quality": "High / Medium / Low",
    "ocf_vs_pat_insight": "Is profit backed by real cash? Explain the gap or alignment with specific reasons — advances received, receivables buildup, inventory, etc.",
    "red_flags": ["Specific FCF concern 1", "Working capital trap signal", "Capex intensity concern if applicable"]
  }},

  "balance_sheet_deep_dive": {{
    "asset_quality": "What are the major assets? Are they productive? Any impairment risk?",
    "debt_profile": "Maturity profile, cost of debt, secured vs unsecured breakdown if available",
    "working_capital_insight": "Receivables days, payable days, inventory days if calculable. Is working capital a cash trap?",
    "hidden_strengths": ["Non-obvious BS strength 1", "Hidden asset or reserve 2"],
    "hidden_risks": ["Non-obvious risk 1 with explanation", "Contingent liability concern 2"],
    "total_debt": "EXTRACT",
    "net_worth": "EXTRACT",
    "debt_to_equity": "CALCULATE",
    "interest_coverage": "CALCULATE",
    "debt_comfort_level": "Comfortable / Moderate / Stressed"
  }},

  "growth_quality": {{
    "revenue_growth_context": "Is growth organic or inorganic? Volume-led or price-led? Sustainable or one-time?",
    "profit_growth_context": "Is profit growing faster or slower than revenue? What explains the divergence?",
    "margin_trend": "Expanding / Compressing / Stable — and what is the structural reason?",
    "growth_outlook": "Accelerating / Stable / Decelerating / Uncertain",
    "catalysts": ["Specific company-relevant growth trigger 1", "Catalyst 2 — not generic"],
    "headwinds": ["Specific risk to growth 1 with reasoning", "Headwind 2 — not generic"]
  }},

  "industry_context": {{
    "sector_tailwinds": ["Industry tailwind 1 relevant to this company", "Tailwind 2"],
    "sector_headwinds": ["Industry headwind 1", "Headwind 2"],
    "competitive_position": "Where does this company sit vs named peers? Is it gaining or losing ground?",
    "peer_benchmarks": "Compare key margins/ratios vs named peers in the same sector",
    "regulatory_environment": "Any policy, regulatory, or government dependency that materially impacts outlook"
  }},

  "red_flags": [
    {{
      "flag": "Specific, non-generic red flag title",
      "severity": "High / Medium / Low",
      "explanation": "Exactly what the concern is and why it matters to an investor",
      "what_to_watch": "Specific metric or event that would confirm or dismiss this risk"
    }}
  ],

  "strengths_and_moats": [
    {{
      "strength": "Specific competitive strength",
      "why_it_matters": "Why this is a genuine durable moat — not just a positive data point",
      "risk_to_moat": "What could erode this advantage?"
    }}
  ],

  "valuation_context": {{
    "note": "Valuation data not provided in document. Based on financials alone:",
    "book_value_per_share": "Calculate if share count available",
    "pb_ratio": "If market price available",
    "earnings_quality": "High / Medium / Low — and why",
    "analyst_comment": "Based on earnings quality, growth trajectory, and balance sheet strength, is the company likely to command a premium or discount to sector peers? Why?"
  }},

  "investor_faq": [
    {{
      "question": "Highly specific question a real investor would ask about THIS company",
      "answer": "Direct, expert, 2-4 sentence answer using actual numbers from the document"
    }},
    {{
      "question": "Second specific investor question",
      "answer": "Direct expert answer"
    }},
    {{
      "question": "Third specific investor question",
      "answer": "Direct expert answer"
    }},
    {{
      "question": "Fourth specific investor question",
      "answer": "Direct expert answer"
    }},
    {{
      "question": "Fifth specific investor question — focus on the biggest risk",
      "answer": "Direct expert answer"
    }}
  ],

  "key_monitorables": [
    {{
      "metric": "Specific metric to track",
      "why": "Why this is the most important forward indicator for this company",
      "trigger": "Specific threshold or event that would signal a positive or negative turn"
    }},
    {{
      "metric": "Second monitorable",
      "why": "Reasoning specific to this company's business model",
      "trigger": "What to watch for"
    }},
    {{
      "metric": "Third monitorable",
      "why": "Specific reasoning",
      "trigger": "Specific trigger threshold"
    }}
  ],

  "profitability": {{
    "analysis": "Detailed analysis with actual numbers and business model context",
    "gross_margin_current": "Calculate or extract %",
    "gross_margin_previous": "ACTUAL %",
    "net_margin_current": "MUST calculate PAT/Revenue",
    "net_margin_previous": "ACTUAL %",
    "ebitda_margin_current": "MUST calculate",
    "ebitda_margin_previous": "ACTUAL %",
    "roe": "MUST calculate PAT/Equity × 100",
    "roa": "MUST calculate PAT/Assets × 100",
    "key_cost_drivers": ["Actual cost item 1 with real numbers", "Cost driver 2 with trend"]
  }},

  "liquidity": {{
    "analysis": "Analysis with real numbers and working capital context",
    "current_ratio": "CALCULATE CA/CL",
    "quick_ratio": "Calculate if data available",
    "cash_position": "EXTRACT Cash and Equivalents",
    "operating_cash_flow": "EXTRACT from Cash Flow Statement",
    "free_cash_flow": "OCF - Capex if available",
    "day_to_day_assessment": "Smooth / Adequate / Tight"
  }},

  "highlights": [
    "Specific strength 1 with actual numbers — not generic",
    "Specific strength 2 with context",
    "Specific strength 3",
    "Specific strength 4",
    "Specific strength 5"
  ],

  "risks": [
    "Specific risk 1 with actual reasoning tied to the numbers — not generic",
    "Specific risk 2",
    "Specific risk 3",
    "Specific risk 4",
    "Specific risk 5"
  ],

  "what_to_watch": [
    "Specific watch item 1 for the next reporting period",
    "Specific watch item 2",
    "Specific watch item 3"
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL REMINDERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- NEVER say "Not reported" without exhaustively searching the full document
- ALWAYS calculate ratios from available raw data
- Rating MUST match score per calibration rules above
- Use REAL extracted numbers everywhere — zero placeholders
- Risks and strengths must be COMPANY-SPECIFIC — never generic boilerplate
- The investor_faq questions must be ones a real investor would genuinely ask about THIS specific company
- The bottom_line must be one sentence that is memorable, direct, and quotable
- The headline must be punchy enough to stand alone as a news headline

FINANCIAL DOCUMENT:
{{snippet}}"""

# FIXED AI RUNNERS - Replace in your server_v12.py starting at line 660

# AI RUNNERS WITH WORKING MODELS (Feb 2026)

def _sync_gemini(text: str) -> dict:
    """
    Use new google-genai package instead of deprecated google.generativeai
    Only use models that are confirmed working
    """
    try:
        # Use new API
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Working models in order of preference
        models_to_try = [
            "gemini-2.0-flash-exp",  # Latest experimental
            "gemini-1.5-pro",        # Stable production
            "gemini-1.5-flash",      # Fast and reliable
        ]
        
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=build_prompt(text),
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=8192,
                    )
                )
                
                raw_text = response.text
                logger.info(f"✓ Gemini {model_name}: {len(raw_text)} chars")
                return safe_parse_json(raw_text)
                
            except Exception as e:
                err_str = str(e)
                logger.warning(f"Gemini {model_name} failed: {err_str[:150]}")
                
                # If quota exceeded, try next model immediately
                if "429" in err_str or "quota" in err_str.lower():
                    continue
                    
                # If model not found, try next
                if "404" in err_str or "not found" in err_str.lower():
                    continue
                    
        raise Exception("All Gemini models failed")
        
    except ImportError:
        # Fallback to old API if new one not available
        logger.warning("New google-genai package not found, using old API")
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(build_prompt(text))
        return safe_parse_json(resp.text)


# GROQ - Use only currently active models (Feb 2026)
GROQ_MODELS_ACTIVE = [
    "llama-3.3-70b-versatile",  # Primary - 128k context
    "llama-3.2-90b-vision-preview",  # Fallback - latest
    "gemma2-9b-it",  # Fast fallback
]

def _sync_groq(text: str) -> dict:
    """Use only active Groq models with proper error handling"""
    from groq import Groq
    
    gc = Groq(api_key=GROQ_API_KEY)
    prompt = build_prompt(text)
    
    # Reduce prompt size if too large
    if len(prompt) > 30000:
        logger.warning(f"Prompt too large ({len(prompt)} chars), truncating to 25000")
        prompt = prompt[:25000] + "\n\n[Document truncated due to size limits]"
    
    for model in GROQ_MODELS_ACTIVE:
        try:
            resp = gc.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=8192
            )
            raw = resp.choices[0].message.content
            logger.info(f"✓ Groq {model}: {len(raw)} chars")
            return safe_parse_json(raw)
            
        except Exception as ex:
            err_str = str(ex)
            logger.warning(f"Groq {model} failed: {err_str[:150]}")
            
            # Skip if rate limited or model decommissioned
            if "429" in err_str or "rate limit" in err_str.lower():
                continue
            if "400" in err_str or "decommissioned" in err_str.lower():
                continue
            if "413" in err_str or "too large" in err_str.lower():
                continue
                
    raise Exception("All Groq models failed or unavailable")


def _sync_together(text: str) -> dict:
    """Together AI with working free models"""
    key = os.getenv("TOGETHER_API_KEY", "")
    if not key:
        raise Exception("No TOGETHER_API_KEY")
    
    import httpx
    
    # Use free tier models
    models = [
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    ]
    
    for model in models:
        try:
            resp = httpx.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": build_prompt(text)}],
                    "temperature": 0.1,
                    "max_tokens": 8192
                },
                timeout=90
            )
            
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                logger.info(f"✓ Together {model}: {len(raw)} chars")
                return safe_parse_json(raw)
            else:
                logger.warning(f"Together {model} failed: {resp.status_code}")
                
        except Exception as e:
            logger.warning(f"Together {model} error: {str(e)[:150]}")
            
    raise Exception("All Together AI models failed")


def _sync_openrouter(text: str) -> dict:
    """OpenRouter with currently available free models"""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise Exception("No OPENROUTER_API_KEY")
    
    import httpx
    import time
    
    # Updated list of working free models (Feb 2026)
    models = [
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "qwen/qwen-2.5-7b-instruct:free",
    ]
    
    for model in models:
        for attempt in range(2):
            try:
                resp = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "HTTP-Referer": "https://finsight-vert.vercel.app",
                        "X-Title": "FinSight",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": build_prompt(text)}],
                        "temperature": 0.1,
                        "max_tokens": 8192
                    },
                    timeout=90
                )
                
                if resp.status_code == 429 and attempt == 0:
                    logger.warning(f"OpenRouter {model} rate limited, waiting 15s...")
                    time.sleep(15)
                    continue
                    
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    logger.info(f"✓ OpenRouter {model}: {len(raw)} chars")
                    return safe_parse_json(raw)
                else:
                    logger.warning(f"OpenRouter {model}: HTTP {resp.status_code}")
                    break  # Try next model
                    
            except Exception as e:
                logger.warning(f"OpenRouter {model} error: {str(e)[:150]}")
                break
                
    raise Exception("All OpenRouter models failed")


# MAIN ANALYSIS ORCHESTRATOR
async def run_analysis(text: str) -> dict:
    """
    Try all available AI providers in order of preference
    Returns first successful result
    """
    loop = asyncio.get_event_loop()
    errors = []
    
    # Provider priority order
    providers = [
        ("Gemini", _sync_gemini, GEMINI_API_KEY),
        ("Groq", _sync_groq, GROQ_API_KEY),
        ("Together", _sync_together, os.getenv("TOGETHER_API_KEY", "")),
        ("OpenRouter", _sync_openrouter, os.getenv("OPENROUTER_API_KEY", "")),
    ]
    
    for provider_name, func, api_key in providers:
        if not api_key:
            logger.info(f"⊘ {provider_name} skipped (no API key)")
            continue
            
        try:
            logger.info(f"→ Trying {provider_name}...")
            result = await loop.run_in_executor(executor, func, text)
            logger.info(f"✓ {provider_name} succeeded!")
            return result
            
        except Exception as e:
            error_msg = str(e)[:200]
            logger.warning(f"✗ {provider_name} failed: {error_msg}")
            errors.append(f"{provider_name}: {error_msg}")
    
    # All providers failed
    error_summary = " | ".join(errors) if errors else "No API keys configured"
    raise Exception(f"All AI providers failed. {error_summary}")
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