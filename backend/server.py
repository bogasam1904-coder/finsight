import os, uuid, logging, json, io, asyncio, httpx, re, requests
from collections import defaultdict
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

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE    = "https://financialmodelingprep.com/api"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET      = os.getenv("JWT_SECRET", "finsight-secret-key-2024")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 30
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")

executor = ThreadPoolExecutor(max_workers=4)
app = FastAPI(title="FinSight API v14")

# ─── CORS ────────────────────────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        r = Response()
        r.headers.update({
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS,PATCH",
            "Access-Control-Allow-Headers": "Authorization,Content-Type,Accept,X-Requested-With",
            "Access-Control-Max-Age": "86400",
        })
        return r
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS,PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type,Accept,X-Requested-With"
    return response

# ─── DB ──────────────────────────────────────────────────────────────────────
mongo_client  = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db            = mongo_client.finsight
users_col     = db.users
analyses_col  = db.analyses
companies_col = db.companies

# ─── AUTH ────────────────────────────────────────────────────────────────────
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

# ─── MODELS ──────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str; email: str; password: str

class LoginRequest(BaseModel):
    email: str; password: str

class AnalyzeFromURLRequest(BaseModel):
    pdf_url: str; filename: str; source: str

class PDFRequest(BaseModel):
    html: str

# ─── HEADERS ─────────────────────────────────────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
NSE_HEADERS = {**BROWSER_HEADERS, "Referer": "https://www.nseindia.com/", "Origin": "https://www.nseindia.com", "Host": "www.nseindia.com"}
BSE_HEADERS = {**BROWSER_HEADERS, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}


# ─── COMPANY MASTER SYNC ─────────────────────────────────────────────────────
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


# ─── FILING HELPERS ──────────────────────────────────────────────────────────
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
            r = await c.get(
                f"https://www.nseindia.com/api/annual-reports?symbol={symbol}&issuer={symbol}&type=annual-report",
                headers=NSE_HEADERS)
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
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
                    return filings
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
        from_dt = (_date.today() - timedelta(days=1825)).strftime("%Y%m%d")

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
                if r.status_code != 200: continue
                items = r.json().get("Table", [])
                for item in items[:max_items]:
                    pdf_name = item.get("ATTACHMENTNAME", "").strip()
                    if not pdf_name: continue
                    title = item.get("SUBJECT") or item.get("CATEGORYNAME") or "Financial Results"
                    candidates = _pdf_candidates(pdf_name)
                    working_url = None
                    for candidate in candidates:
                        if await verify_pdf_url(c, candidate):
                            working_url = candidate
                            break
                    if not working_url:
                        working_url = candidates[0]
                    filings.append({"title": title, "date": item.get("NEWS_DT", ""),
                                    "pdf_url": working_url,
                                    "type": forced_type or _classify_filing(title),
                                    "source": "BSE", "symbol": symbol, "bse_code": bse_code})
        return filings[:15]
    except Exception as e:
        logger.warning(f"BSE filings error for {bse_code}: {e}")
    return []


# ─── PDF PAGE CLASSIFICATION ─────────────────────────────────────────────────

# Pages in Indian quarterly filings that must be EXCLUDED from data extraction:
# - Auditor review report pages: contain phrases like "total revenues of Rs. X crore"
#   which are NARRATIVE references to subsidiary numbers, NOT the actual P&L totals.
#   The AI consistently mistakes these auditor-quoted numbers for consolidated figures.
# - Cover letter pages
# - Ratio formula explanation pages
# - Subsidiaries/JV/Associates list pages

AUDITOR_POISON_PHRASES = [
    "total revenues of rs",
    "total revenues of ₹",
    "reflect total revenues",
    "total net profit after tax of rs",
    "total comprehensive income of rs",
    "group's share of profit",
    "reviewed by one of us",
    "independently reviewed",
    "our conclusion on the statement",
    "standard on review engagements",
    "sre 2410",
    "chartered accountants",
    "firm's registration no",
    "membership no",
    "udin:",
    "list of subsidiaries",
    "list of joint ventures",
    "list of associates",
    "ceased to be a subsidiary",
    "merged with another subsidiary",
    "formulae for computation of ratios",
    "deloitte haskins",
    "chaturvedi & shah",
    "dear sirs",
    "pursuant to regulation 33",
    "sebi (listing obligation",
    "independent auditor",
    "review report",
    "moderate assurance",
]

FINANCIAL_TABLE_PHRASES = [
    "revenue from operations",
    "profit before tax",
    "profit after tax",
    "total income",
    "finance costs",
    "depreciation",
    "employee benefits expense",
    "other expenses",
    "total expenses",
    "earnings per equity share",
    "paid-up equity share capital",
    "net worth",
    "debt service coverage",
    "interest service coverage",
    "debt equity ratio",
    "current ratio",
    "operating margin",
    "net profit margin",
    "segment results",
    "segment assets",
    "segment liabilities",
    "oil to chemicals",
    "digital services",
    "value of sales",
    "cost of materials",
    "purchases of stock",
    "changes in inventories",
    "excise duty",
    "deferred tax",
    "current tax",
]

CONSOLIDATED_MARKERS = [
    "unaudited consolidated financial results",
    "consolidated financial results",
    "consolidated statement",
    "consolidated segment",
]

STANDALONE_MARKERS = [
    "unaudited standalone financial results",
    "standalone financial results",
    "standalone statement",
    "standalone segment",
]


def _score_page_for_extraction(page_text: str) -> dict:
    """
    Returns a detailed score dict for a page.
    Pages with high auditor_poison scores must be excluded.
    Only pages with financial_table scores should be used.
    """
    t = page_text.lower()

    poison_hits = sum(1 for p in AUDITOR_POISON_PHRASES if p in t)
    table_hits  = sum(1 for p in FINANCIAL_TABLE_PHRASES if p in t)
    consol_hits = sum(1 for p in CONSOLIDATED_MARKERS if p in t)
    standalone_hits = sum(1 for p in STANDALONE_MARKERS if p in t)

    # A page is "poisoned" if it has many auditor phrases and few actual table rows
    # Key signal: auditor pages mention specific numbers in prose sentences
    is_auditor_narrative = (
        ("reflect total revenues" in t or "total revenues of rs" in t) or
        ("udin:" in t) or
        ("firm's registration no" in t) or
        ("list of subsidiaries" in t and table_hits < 2) or
        ("formulae for computation of ratios" in t and "revenue from operations" not in t) or
        (poison_hits >= 4 and table_hits < 3)
    )

    return {
        "poison_hits": poison_hits,
        "table_hits": table_hits,
        "consol_hits": consol_hits,
        "standalone_hits": standalone_hits,
        "is_auditor_narrative": is_auditor_narrative,
        "net_score": (table_hits * 3) + (consol_hits * 2) - (poison_hits * 2) - (standalone_hits * 1),
    }


def _select_financial_pages(raw_bytes: bytes) -> list:
    """
    Select only pages containing actual financial tables.
    CRITICAL: Exclude auditor review report pages which contain
    narrative references to numbers (e.g. "total revenues of Rs. 3,04,299 crore")
    that are NOT the consolidated P&L totals.
    """
    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    total  = len(reader.pages)

    page_scores = []
    has_consolidated = False

    for i, page in enumerate(reader.pages):
        t = (page.extract_text() or "")
        score_info = _score_page_for_extraction(t)
        page_scores.append((i, score_info))
        if score_info["consol_hits"] > 0 and not score_info["is_auditor_narrative"]:
            has_consolidated = True

    selected = set()

    for i, info in page_scores:
        # ALWAYS skip auditor narrative pages — they poison AI with wrong numbers
        if info["is_auditor_narrative"]:
            logger.info(f"Page {i+1}: EXCLUDED (auditor narrative, poison_hits={info['poison_hits']})")
            continue

        # Skip standalone when consolidated exists
        if has_consolidated and info["standalone_hits"] > 0 and info["consol_hits"] == 0:
            logger.info(f"Page {i+1}: EXCLUDED (standalone, consolidated exists)")
            continue

        # Include pages with meaningful financial table content
        if info["net_score"] >= 3 or (info["table_hits"] >= 3 and not info["is_auditor_narrative"]):
            selected.add(i)
            logger.info(f"Page {i+1}: SELECTED (net_score={info['net_score']}, table_hits={info['table_hits']}, consol={info['consol_hits']})")

    # Safety cap: BSE filings have auditor pages 1-9, real data from page 10
    if total > 20:
        selected = {i for i in selected if i < 20}

    result = sorted(selected)
    logger.info(f"PDF: {total} pages, consolidated={has_consolidated}, selected: {[p+1 for p in result]}")
    return result


def _detect_currency_unit(text: str) -> str:
    t = text[:4000].lower()
    if any(x in t for x in ["₹ in crore", "rs. in crore", "inr crore", "in crores",
                              "(crore)", "crore each", "except per share", "crore, except",
                              "in crore, except"]):
        return "INR Crores"
    if any(x in t for x in ["₹ in lakh", "rs. in lakh", "inr lakh", "in lakhs", "(lakh)"]):
        return "INR Lakhs"
    if any(x in t for x in ["usd million", "$ million", "in millions", "us$ million"]):
        return "USD Millions"
    if any(x in t for x in ["usd billion", "$ billion", "in billions"]):
        return "USD Billions"
    return "INR Crores"


def _parse_period_header(row: list) -> list:
    row_text = " ".join(str(c) for c in row if c).lower()
    PERIOD_PATTERNS = [
        r"dec['\s\-]*2[0-9]", r"sep['\s\-]*2[0-9]", r"mar['\s\-]*2[0-9]",
        r"jun['\s\-]*2[0-9]", r"q[1-4]\s*fy\s*2[0-9]", r"fy\s*20[0-9]{2}",
        r"31st", r"30th", r"quarter ended", r"year ended", r"nine months", r"half.?year",
    ]
    hits = sum(1 for p in PERIOD_PATTERNS if re.search(p, row_text))
    if hits >= 2:
        return [str(c).strip().replace("\n", " ") for c in row]
    return []


def _build_structured_financials(raw_bytes: bytes, page_indices: list) -> tuple:
    """
    Parse financial tables with column-aware extraction.
    Returns (structured_text, currency).
    """
    import pdfplumber

    result_sections = []
    currency = "INR Crores"
    col_headers = []
    current_col_idx = 1
    prior_yr_col_idx = None

    try:
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page_idx in page_indices:
                if page_idx >= len(pdf.pages):
                    continue
                page = pdf.pages[page_idx]
                raw_text = page.extract_text() or ""

                if page_idx < 5:
                    detected_currency = _detect_currency_unit(raw_text)
                    if detected_currency != "INR Crores":
                        currency = detected_currency
                    elif "in crore" in raw_text.lower():
                        currency = "INR Crores"

                tables = page.extract_tables()
                if not tables:
                    if raw_text.strip():
                        result_sections.append(f"--- PAGE {page_idx+1} (text) ---\n{raw_text.strip()}")
                    continue

                page_rows = []
                for table in tables:
                    for row in table:
                        if not row or not any(row):
                            continue
                        cleaned = [str(c).strip().replace("\n", " ") if c else "" for c in row]

                        detected_periods = _parse_period_header(cleaned)
                        if detected_periods:
                            col_headers = detected_periods
                            current_col_idx = 1
                            prior_yr_col_idx = None
                            if len(col_headers) > 1:
                                cur_label = col_headers[1].lower() if len(col_headers) > 1 else ""
                                month_match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', cur_label)
                                cur_month = month_match.group(1) if month_match else ""
                                for ci in range(2, len(col_headers)):
                                    lbl = col_headers[ci].lower()
                                    if cur_month and cur_month in lbl and ci != current_col_idx:
                                        prior_yr_col_idx = ci
                                        break
                                if prior_yr_col_idx is None and len(col_headers) > 3:
                                    prior_yr_col_idx = 3
                            continue

                        label = cleaned[0] if cleaned else ""
                        if not label or label in ("None", "", "Particulars", "Sr.", "Sr. No", "Sr"):
                            continue
                        if all(c in ("", "-", "—", "None") for c in cleaned[1:]):
                            continue

                        def safe_val(row, idx):
                            if idx is not None and idx < len(row) and row[idx] not in ("", "None", "-", "—"):
                                return row[idx]
                            return None

                        cur_val = safe_val(cleaned, current_col_idx)
                        prev_val = safe_val(cleaned, prior_yr_col_idx)

                        cur_period = col_headers[current_col_idx] if col_headers and current_col_idx < len(col_headers) else "Current Period"
                        prev_period = col_headers[prior_yr_col_idx] if col_headers and prior_yr_col_idx and prior_yr_col_idx < len(col_headers) else "Prior Year Same Period"

                        if cur_val:
                            entry = f"{label}: {cur_period}={cur_val}"
                            if prev_val:
                                entry += f" | {prev_period}={prev_val}"
                            for extra_idx in [4, 5]:
                                extra_val = safe_val(cleaned, extra_idx)
                                extra_lbl = col_headers[extra_idx] if col_headers and extra_idx < len(col_headers) else f"Col{extra_idx}"
                                if extra_val and extra_idx not in ([current_col_idx] + ([prior_yr_col_idx] if prior_yr_col_idx else [])):
                                    entry += f" | {extra_lbl}={extra_val}"
                                    break
                            page_rows.append(entry)
                        else:
                            non_empty = [c for c in cleaned if c and c not in ("None",)]
                            if len(non_empty) >= 2:
                                page_rows.append(" | ".join(non_empty))

                if page_rows:
                    result_sections.append(f"--- PAGE {page_idx+1} ---\n" + "\n".join(page_rows))
                elif raw_text.strip():
                    result_sections.append(f"--- PAGE {page_idx+1} (text) ---\n{raw_text.strip()}")

    except Exception as e:
        logger.warning(f"Structured extraction failed: {e}")
        return "", "INR Crores"

    structured = "\n\n".join(result_sections)
    logger.info(f"Structured extraction: {len(structured):,} chars, currency={currency}")
    return structured, currency


# ─── DETERMINISTIC EXTRACTOR ─────────────────────────────────────────────────
# Philosophy: AI does interpretation + writing. NOT data extraction.
# Every number shown to a user must be traceable to a specific row/table in the filing.
# If we can't find it deterministically → mark as "Not available" rather than let AI guess.

# P&L row labels to look for (case-insensitive partial match)
_PL_ROW_MAP = {
    "revenue":          ["revenue from operations", "net revenue", "total revenue", "revenue from operation"],
    "total_income":     ["total income"],
    "other_income":     ["other income"],
    "total_expenses":   ["total expenses", "total expenditure"],
    "ebitda":           ["ebitda"],
    "depreciation":     ["depreciation", "amortisation", "amortization"],
    "finance_costs":    ["finance costs", "interest expense", "finance cost"],
    "pbt":              ["profit before tax", "profit/(loss) before tax"],
    "tax":              ["tax expense", "income tax expense", "current tax"],
    "pat_total":        ["profit after tax", "profit/(loss) after tax", "net profit after tax", "profit for the period", "profit for the quarter"],
    "pat_owners":       ["profit attributable to owners", "attributable to owners", "attributable to equity holders", "owners of the company", "owners of the parent"],
    "pat_minority":     ["non-controlling interest", "minority interest", "attributable to non-controlling"],
    "eps_basic":        ["basic eps", "basic earnings per share", "earnings per share - basic"],
    "eps_diluted":      ["diluted eps", "diluted earnings per share", "earnings per share - diluted"],
}

# Ratios section row labels
_RATIO_ROW_MAP = {
    "debt_service_coverage":     ["debt service coverage"],
    "interest_coverage":         ["interest service coverage", "interest coverage"],
    "debt_equity":               ["debt equity ratio", "debt-equity ratio", "d/e ratio"],
    "current_ratio":             ["current ratio"],
    "long_term_debt_wc":         ["long-term debt to working capital", "long term debt to working capital"],
    "current_liability_ratio":   ["current liability ratio"],
    "total_debt_to_assets":      ["total debts to total assets", "total debt to total assets"],
    "debtors_turnover":          ["debtors turnover", "trade receivables turnover"],
    "inventory_turnover":        ["inventory turnover"],
    "operating_margin":          ["operating profit margin", "operating margin"],
    "net_profit_margin":         ["net profit margin", "net margin"],
    "return_on_equity":          ["return on equity", "return on net worth"],
    "return_on_assets":          ["return on assets", "return on total assets"],
    "return_on_capital":         ["return on capital employed", "roce"],
}

# Segment EBITDA section
_SEGMENT_KEYWORDS = ["segment", "ebitda", "segment result", "profit from segment"]

# Balance sheet rows
_BS_ROW_MAP = {
    "total_assets":     ["total assets"],
    "total_equity":     ["total equity", "equity attributable", "shareholders equity", "total equity and liabilities"],
    "net_worth":        ["net worth", "shareholders' funds", "total equity"],
    "total_borrowings": ["total borrowings", "borrowings", "long-term borrowings", "short-term borrowings"],
    "total_liabilities":["total liabilities", "total equity and liabilities"],
}


def _clean_num(val: str) -> str:
    """Clean a cell value — strip whitespace, handle parentheses as negative."""
    if not val:
        return ""
    v = str(val).strip().replace(",", "").replace(" ", "")
    if v.startswith("(") and v.endswith(")"):
        v = "-" + v[1:-1]
    return v


def _parse_float(val: str):
    """Parse a cell value to float, return None if unparseable."""
    v = _clean_num(val)
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _match_row_label(label: str, patterns: list) -> bool:
    """Check if a row label matches any of the given patterns (case-insensitive)."""
    label_lower = label.lower().strip()
    return any(p in label_lower for p in patterns)


def _extract_line_values(line: str) -> list:
    """Extract all numeric values from a text line (handles Indian comma formatting & negatives)."""
    nums = re.findall(r'\([\d,]+(?:\.\d+)?\)|[\d,]+(?:\.\d+)?', line)
    result = []
    for n in nums:
        clean = n.strip('()').replace(',', '')
        if clean:
            result.append('-' + clean if n.startswith('(') else clean)
    return result


def _get_large_nums(line: str) -> list:
    """Extract numbers > 100 (financial figures, not ratios)."""
    result = []
    for n in _extract_line_values(line):
        try:
            if abs(float(n)) > 100:
                result.append(n)
        except:
            pass
    return result


def _fix_font_encoded_number(s: str) -> str:
    """
    Fix font-encoding corruption common in BSE filing PDFs.
    e.g. "J,912" -> "7,912"  (J is encoded as digit 7)
         "22;1s1" -> "22,161" (semicolon for comma, s for 6)
         "-Aoa,245:" -> likely garbage, return empty
    """
    # Replace known glyph substitutions
    s = s.replace(';', ',').replace('J', '7').replace('s', '6').replace('l', '1')
    s = s.strip(':').strip()
    # If it still contains non-numeric chars (other than . , - () ), it's garbled
    if re.search(r'[A-Za-z]', s):
        return ''
    return s


def _get_large_nums_with_fallback(line: str) -> tuple:
    """
    Extract large numbers from a line with sanity checking.
    Returns (current_q_val, prior_q_val, sep_q_val).
    current_q_val is empty if first column appears corrupted/fragmented.
    Detects font-encoding corruption where first column is dramatically smaller
    than second column (a telltale sign of partial/garbled extraction).
    """
    tokens = re.findall(r'\([\d,;Jsl]+(?:\.\d+)?\)|[\d,;Jsl]+(?:\.\d+)?', line)
    clean_nums = []
    for t in tokens:
        is_neg = t.startswith('(')
        raw = t.strip('()')
        direct = raw.replace(',', '').replace(';', '')
        try:
            val = float(direct)
            if abs(val) > 100:
                clean_nums.append(('-' if is_neg else '') + str(int(val)))
                continue
        except:
            pass

    if not clean_nums:
        return '', '', ''

    current = clean_nums[0]
    sep_q   = clean_nums[1] if len(clean_nums) > 1 else ''
    prior   = clean_nums[2] if len(clean_nums) > 2 else ''

    # Sanity check: if current is < 30% of sep_q on a large-value line, 
    # it's likely a corrupted fragment (font encoding issue)
    if current and sep_q:
        try:
            c, s = abs(float(current)), abs(float(sep_q))
            if s > 1000 and c < s * 0.30:
                return '', prior, sep_q  # current unreliable
        except:
            pass

    return current, prior, sep_q


def _extract_pl_any_layout(lines: list, page_num: int, log: list) -> dict:
    """
    Extract P&L handling both row-by-row and font-encoding-corrupted layouts.
    BSE filings often have font encoding issues in column 1 (current quarter).
    Falls back to prior quarter (Sep'25) when current quarter column is unreadable.
    """
    # Ordered P&L rows as they appear in Indian quarterly filings
    PL_ORDERED = [
        ("gross_revenue",  ["value of sales & services", "value of sales and services"]),
        ("gst_recovered",  ["less: gst recovered", "less:gst"]),
        ("revenue",        ["revenue from operations"]),
        ("other_income",   ["other income"]),
        ("total_income",   ["total income"]),
        ("cost_materials", ["cost of materials consumed"]),
        ("stock_purchases",["purchases of stock-in-trade"]),
        ("inv_changes",    ["changes in inventories"]),
        ("excise_duty",    ["excise duty"]),
        ("employee_costs", ["employee benefits expense"]),
        ("finance_costs",  ["finance costs"]),
        ("depreciation",   ["depreciation / amortisation", "depreciation/amortisation",
                            "depreciation and amortisation", "depreciation / amortization"]),
        ("other_expenses", ["other expenses"]),
        ("total_expenses", ["total expenses"]),
        ("pbt",            ["profit before tax"]),
        ("current_tax",    ["current tax"]),
        ("deferred_tax",   ["deferred tax"]),
        ("pat_total",      ["profit after tax"]),
    ]

    # Attribution rows appear AFTER pat_total - handle separately
    ATTR_ROWS = [
        ("pat_owners",   ["a) owners of the company", "owners of the company",
                          "a)\towners", "attributable to owners"]),
        ("pat_minority", ["b) non-controlling interest", "non-controlling interest",
                          "b)\tnon-controlling", "minority interest"]),
    ]

    # EPS rows
    EPS_ROWS = [
        ("eps_basic",   ["a) basic (in", "basic (in ₹", "basic (in rs",
                         "a)\tbasic", "basic earnings per"]),
        ("eps_diluted", ["b) diluted (in", "diluted (in ₹", "diluted (in rs",
                         "b)\tdiluted", "diluted earnings per"]),
    ]

    result = {}

    # ── Pass 1: Row-by-row ─────────────────────────────────────────────────────
    # BSE filing column order (pypdf text): Dec25 | Sep25 | Dec24 | 9M-cur | 9M-prior
    # _get_large_nums_with_fallback returns (current, sep_qtr, prior_yr_same_qtr)
    # "prior" for YoY display = prior_yr_same_qtr (index 2 in raw line)
    all_patterns = PL_ORDERED + ATTR_ROWS + EPS_ROWS
    for i, line in enumerate(lines):
        ll = line.lower().strip()
        for key, patterns in all_patterns:
            if key in result:
                continue
            if not any(p in ll for p in patterns):
                continue
            cur, sep_q, prior_yr = _get_large_nums_with_fallback(line)
            for offset in [1, 2]:
                if cur:
                    break
                if i + offset < len(lines):
                    cur, sep_q, prior_yr = _get_large_nums_with_fallback(lines[i + offset])
            if not cur and sep_q:
                cur = sep_q
                log.append(f"[{key}] col-1 font-corrupted, using col-2 fallback @ P{page_num}L{i+1}")
            if cur:
                result[key] = {
                    "current": cur,
                    "prior": prior_yr if prior_yr else sep_q,
                    "source": f"Page {page_num}, Line {i + 1} (row-by-row)",
                }
                log.append(f"[{key}] = {cur} @ P{page_num}L{i+1} (row-by-row)")
            break

    if len([k for k in result if k in dict(PL_ORDERED)]) >= 4:
        return result  # Row-by-row gave enough rows

    log.append(f"Row-by-row yielded only {len(result)} rows, trying column-first layout")

    # ── Pass 2: Column-first (all labels then all values) ─────────────────────
    matched_keys = []   # [(key, line_idx), ...] in document order
    value_rows = []     # [(nums_list, line_idx), ...] in document order

    for i, line in enumerate(lines):
        ll = line.lower().strip()
        for key, patterns in PL_ORDERED:
            if any(p in ll for p in patterns):
                if not any(mk == key for mk, _ in matched_keys):
                    matched_keys.append((key, i))
                break

    for i, line in enumerate(lines):
        nums = _get_large_nums(line)
        if len(nums) >= 3:  # Real value row has ≥3 columns
            value_rows.append((nums, i))

    log.append(f"Column-first: {len(matched_keys)} label matches, {len(value_rows)} value rows")

    # Zip by position
    result_p2 = {}
    for pos, (key, label_idx) in enumerate(matched_keys):
        if pos < len(value_rows):
            nums, val_idx = value_rows[pos]
            result_p2[key] = {
                "current": nums[0],
                "prior": nums[2] if len(nums) > 2 else "",
                "source": f"Page {page_num}, Label L{label_idx+1}→Values L{val_idx+1} (col-first)",
            }
            log.append(f"[{key}] = {nums[0]} @ col-first L{label_idx+1}→{val_idx+1}")

    # Also try attribution rows with lookahead after pat_total
    pat_line = next((i for i, l in enumerate(lines) if "profit after tax" in l.lower()), None)
    if pat_line is not None:
        for i in range(pat_line, min(pat_line + 10, len(lines))):
            ll = lines[i].lower().strip()
            for key, patterns in ATTR_ROWS + EPS_ROWS:
                if key in result_p2:
                    continue
                if any(p in ll for p in patterns):
                    nums = _get_large_nums(lines[i])
                    for offset in [1, 2]:
                        if nums:
                            break
                        if i + offset < len(lines):
                            nums = _get_large_nums(lines[i + offset])
                    if nums:
                        result_p2[key] = {
                            "current": nums[0],
                            "prior": nums[2] if len(nums) > 2 else "",
                            "source": f"Page {page_num}, Line {i+1} (attr)",
                        }

    # Return whichever pass got more results
    if len(result_p2) >= len(result):
        return result_p2
    return result


def _extract_deterministic(raw_bytes: bytes, page_indices: list) -> dict:
    """
    Deterministically extract key financial numbers from a BSE/NSE filing PDF.
    Handles both row-by-row and column-first pypdf extraction layouts.
    """
    result = {
        "company_name": "",
        "currency": "INR Crores",
        "period": "",
        "prior_period": "",
        "pl": {},
        "ratios": {},
        "segments": {},
        "balance_sheet": {},
        "is_quarterly": True,
        "filing_type": "Quarterly",
        "extraction_log": [],
    }
    log = result["extraction_log"]

    # ── Read pages ────────────────────────────────────────────────────────────
    page_texts = {}
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        for page_idx in page_indices:
            if page_idx >= len(reader.pages):
                continue
            page_texts[page_idx] = reader.pages[page_idx].extract_text() or ""
    except Exception as e:
        log.append(f"PDF read error: {e}")
        return result

    all_text = "\n".join(page_texts.values())

    # ── Meta ──────────────────────────────────────────────────────────────────
    result["currency"] = _detect_currency_unit(all_text)
    result["company_name"] = _extract_company_name_v2(all_text)

    t_lower = all_text.lower()
    if "nine months" in t_lower:
        result["filing_type"] = "Quarterly (Nine Months YTD)"
    elif "year ended" in t_lower and "nine months" not in t_lower:
        result["is_quarterly"] = False
        result["filing_type"] = "Annual"

    period_m = re.search(
        r"(?:quarter|nine months|year)[\s\w]*ended[\s\w]*(3[01](?:st|nd|rd|th)?\s+(?:dec|sep|mar|jun)['\.\s]*\d{2,4})",
        all_text, re.IGNORECASE
    )
    if period_m:
        result["period"] = period_m.group(1).strip()

    # ── Categorise pages ──────────────────────────────────────────────────────
    consolidated_pl_pages = []
    ratio_pages = []
    segment_pages = []

    for page_idx, text in page_texts.items():
        t = text.lower()
        is_segment_page = "segment" in t[:300] or "segment value of sales" in t
        if "unaudited consolidated" in t and not is_segment_page:
            consolidated_pl_pages.append(page_idx)
        if "ratios" in t and ("debt equity" in t or "operating margin" in t):
            ratio_pages.append(page_idx)
        if is_segment_page and ("ebitda" in t or "segment results" in t):
            segment_pages.append(page_idx)

    log.append(f"Consol P&L pages: {[p+1 for p in consolidated_pl_pages]}")
    log.append(f"Ratio pages: {[p+1 for p in ratio_pages]}")

    pl_pages = consolidated_pl_pages or list(page_texts.keys())

    # ── Extract P&L ───────────────────────────────────────────────────────────
    for page_idx in pl_pages:
        lines = page_texts[page_idx].split("\n")
        pl_result = _extract_pl_any_layout(lines, page_idx + 1, log)
        for k, v in pl_result.items():
            if k not in result["pl"]:
                result["pl"][k] = v

    # ── Revenue fallback from segment page (always clean) ────────────────────
    # BSE filings have font encoding issues in P&L col 1; segment page is cleaner
    if "revenue" not in result["pl"] or result["pl"]["revenue"].get("source","").endswith("[Sep25-fallback]"):
        seg_pages = segment_pages or list(page_texts.keys())
        for page_idx in seg_pages:
            lines = page_texts[page_idx].split("\n")
            for i, line in enumerate(lines):
                ll = line.lower().strip()
                if "revenue from operations" in ll:
                    current, prior, sep25 = _get_large_nums_with_fallback(line)
                    for offset in [1, 2]:
                        if current: break
                        if i+offset < len(lines):
                            current, prior, sep25 = _get_large_nums_with_fallback(lines[i+offset])
                    if current:
                        result["pl"]["revenue"] = {
                            "current": current, "prior": prior,
                            "source": f"Page {page_idx+1}, Line {i+1} (from segment page)"
                        }
                        log.append(f"[revenue] = {current} from segment page")
                        break

    # ── Net Worth ─────────────────────────────────────────────────────────────
    for page_idx in pl_pages:
        lines = page_texts[page_idx].split("\n")
        for i, line in enumerate(lines):
            ll = line.lower()
            if "net worth" in ll and ("including" in ll or "retained" in ll):
                nums = _get_large_nums(line)
                for offset in [1, 2]:
                    if nums: break
                    if i+offset < len(lines):
                        nums = _get_large_nums(lines[i+offset])
                if nums:
                    result["balance_sheet"]["net_worth"] = {
                        "current": nums[0], "prior": nums[2] if len(nums)>2 else "",
                        "source": f"Page {page_idx+1}, Line {i+1}"
                    }
                    log.append(f"[net_worth] = {nums[0]}")
                    break

    # ── Ratios ────────────────────────────────────────────────────────────────
    RATIO_ROWS = [
        ("debt_service_coverage", ["debt service coverage"]),
        ("interest_coverage",     ["interest service coverage", "interest coverage ratio"]),
        ("debt_equity",           ["debt equity ratio"]),
        ("current_ratio",         ["current ratio"]),
        ("long_term_debt_wc",     ["long-term debt to working capital", "long term debt to working"]),
        ("current_liability",     ["current liability ratio"]),
        ("total_debt_assets",     ["total debts to total assets", "total debt to total assets"]),
        ("debtors_turnover",      ["debtors turnover"]),
        ("inventory_turnover",    ["inventory turnover"]),
        ("operating_margin",      ["operating margin"]),
        ("net_profit_margin",     ["net profit margin"]),
    ]

    for page_idx in (ratio_pages or list(page_texts.keys())):
        lines = page_texts[page_idx].split("\n")
        in_ratios = False
        for i, line in enumerate(lines):
            ll = line.lower().strip()
            if ll == "ratios" or re.match(r'^[a-l]\)\s', ll):
                in_ratios = True
            if not in_ratios:
                continue
            if any(x in ll for x in ["notes", "registered office", "segment"]) and len(ll) < 30:
                in_ratios = False
                continue
            for key, patterns in RATIO_ROWS:
                if key in result["ratios"]:
                    continue
                if any(p in ll for p in patterns):
                    nums = _extract_line_values(line)
                    if nums:
                        result["ratios"][key] = {
                            "current": nums[0],
                            "prior": nums[2] if len(nums) > 2 else (nums[1] if len(nums) > 1 else ""),
                            "source": f"Page {page_idx+1}, Line {i+1}",
                        }
                        log.append(f"ratio [{key}] = {nums[0]}")
                    break

    # ── Segment EBITDA ────────────────────────────────────────────────────────
    SEGMENT_ROWS = [
        ("O2C",             ["oil to chemicals", "- oil to chemicals"]),
        ("Oil & Gas",       ["oil and gas", "- oil and gas"]),
        ("Retail",          ["- retail", "retail*"]),
        ("Digital Services",["digital services", "- digital services"]),
        ("Others",          ["- others"]),
    ]
    for page_idx in (segment_pages or []):
        lines = page_texts[page_idx].split("\n")
        in_ebitda = False
        for i, line in enumerate(lines):
            ll = line.lower().strip()
            if "segment results (ebitda)" in ll:
                in_ebitda = True
                continue
            if "segment results (ebit)" in ll:
                in_ebitda = False
                continue
            if not in_ebitda:
                continue
            for seg, patterns in SEGMENT_ROWS:
                if seg in result["segments"]:
                    continue
                if any(p in ll for p in patterns):
                    nums = _get_large_nums(line)
                    if nums:
                        result["segments"][seg] = {
                            "ebitda": nums[0], "prior": nums[2] if len(nums)>2 else "",
                            "source": f"Page {page_idx+1}, Line {i+1}"
                        }
                        log.append(f"segment [{seg}] = {nums[0]}")
                    break

    logger.info(
        f"Extraction: {len(result['pl'])} P&L, {len(result['ratios'])} ratios, "
        f"company='{result['company_name']}', period='{result['period']}'"
    )
    for entry in log:
        logger.debug(f"  {entry}")
    return result


def _build_verified_block(extracted: dict) -> str:
    """
    Build the VERIFIED DATA BLOCK from deterministically extracted numbers.
    This block is placed at the top of every AI prompt.
    Numbers here are sourced directly from the filing tables — AI must use them as ground truth.
    """
    currency = extracted.get("currency", "INR Crores")
    pl = extracted.get("pl", {})
    ratios = extracted.get("ratios", {})
    segments = extracted.get("segments", {})
    bs = extracted.get("balance_sheet", {})
    company = extracted.get("company_name", "")
    period = extracted.get("period", "")
    prior = extracted.get("prior_period", "")
    is_quarterly = extracted.get("is_quarterly", True)

    def fmt(key, store, label=None):
        if key in store:
            d = store[key]
            lbl = label or d.get("label", key)
            cur = d.get("current", "")
            pri = d.get("prior", "")
            src = d.get("source", "")
            line = f"  {lbl}: {cur} {currency}"
            if pri:
                line += f"  [Prior year same period: {pri}]"
            if src:
                line += f"  [SOURCE: {src}]"
            return line
        return f"  {label or key}: Not found in filing"

    lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        "║  VERIFIED FINANCIAL DATA — EXTRACTED DIRECTLY FROM FILING  ║",
        "║  AI MUST USE THESE NUMBERS. DO NOT SUBSTITUTE OR RECALCULATE ║",
        "╚══════════════════════════════════════════════════════════════╝",
        "",
    ]

    if company:
        lines.append(f"COMPANY: {company}")
    if period:
        lines.append(f"CURRENT PERIOD: {period}   COMPARISON PERIOD: {prior}")
    lines.append(f"CURRENCY: All values in {currency}")
    lines.append(f"FILING TYPE: {extracted.get('filing_type', 'Quarterly')}")
    lines.append("")

    lines.append("━━━ INCOME STATEMENT (from P&L table) ━━━")
    lines.append(fmt("revenue",        pl, "Revenue from Operations"))
    lines.append(fmt("total_income",   pl, "Total Income"))
    lines.append(fmt("other_income",   pl, "Other Income"))
    lines.append(fmt("total_expenses", pl, "Total Expenses"))
    lines.append(fmt("depreciation",   pl, "Depreciation & Amortisation"))
    lines.append(fmt("finance_costs",  pl, "Finance Costs"))
    lines.append(fmt("pbt",            pl, "Profit Before Tax"))
    lines.append(fmt("pat_total",      pl, "PAT (Total incl. Minority)"))
    lines.append(fmt("pat_owners",     pl, "PAT Attributable to Owners ← USE THIS AS NET PROFIT"))
    lines.append(fmt("pat_minority",   pl, "PAT Attributable to Minority"))
    lines.append(fmt("eps_basic",      pl, "Basic EPS"))
    lines.append(fmt("eps_diluted",    pl, "Diluted EPS"))
    lines.append("")

    lines.append("━━━ RATIOS (as printed in filing — DO NOT RECALCULATE) ━━━")
    lines.append(fmt("debt_equity",        ratios, "Debt to Equity Ratio"))
    lines.append(fmt("current_ratio",      ratios, "Current Ratio"))
    lines.append(fmt("interest_coverage",  ratios, "Interest Coverage Ratio"))
    lines.append(fmt("operating_margin",   ratios, "Operating Margin %"))
    lines.append(fmt("net_profit_margin",  ratios, "Net Profit Margin %"))
    lines.append(fmt("return_on_equity",   ratios, "Return on Equity %"))
    lines.append(fmt("return_on_assets",   ratios, "Return on Assets %"))
    lines.append(fmt("debt_service_coverage", ratios, "Debt Service Coverage"))
    lines.append(fmt("debtors_turnover",   ratios, "Debtors Turnover"))
    lines.append(fmt("inventory_turnover", ratios, "Inventory Turnover"))
    lines.append("")

    if bs:
        lines.append("━━━ BALANCE SHEET ━━━")
        lines.append(fmt("total_assets",     bs, "Total Assets"))
        lines.append(fmt("net_worth",        bs, "Net Worth / Equity"))
        lines.append(fmt("total_borrowings", bs, "Total Borrowings"))
        lines.append("")

    if segments:
        lines.append("━━━ SEGMENT EBITDA ━━━")
        for seg_name, seg_data in segments.items():
            src = seg_data.get("source", "")
            cur = seg_data.get("ebitda", "")
            pri = seg_data.get("prior", "")
            line = f"  {seg_name}: {cur}"
            if pri:
                line += f"  [Prior: {pri}]"
            if src:
                line += f"  [SOURCE: {src}]"
            lines.append(line)
        lines.append("")

    if is_quarterly:
        lines.append("━━━ CASH FLOW ━━━")
        lines.append("  QUARTERLY FILING — Cash Flow Statement NOT included in quarterly results.")
        lines.append("  Set ALL cash flow fields to 'Not available in this filing'. Score Cash Flow = 9.")
        lines.append("  DO NOT estimate or fabricate OCF, FCF, Capex from PAT or any other figure.")
        lines.append("")

    lines.append("━━━ AI INSTRUCTIONS ━━━")
    lines.append("1. Every number in your response must come from this VERIFIED block above.")
    lines.append("2. If a field is marked 'Not found in filing' → write 'Not available in this filing'.")
    lines.append("3. NEVER use numbers from the auditor's review report text (subsidiary scope figures).")
    lines.append("4. Net Profit = PAT Attributable to Owners (not total PAT including minority interest).")
    lines.append("5. Ratios are already computed by the company — use them directly, never recalculate.")
    lines.append("6. Your job is to WRITE COMMENTARY on these verified numbers, not find new ones.")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    return "\n".join(lines)


def _extract_company_name_v2(text: str) -> str:
    """Extract company name from top of filing text."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    company_keywords = [
        "limited", "ltd", "ltd.", "corporation", "industries", "technologies",
        "bank", "finance", "energy", "infosys", "wipro", "tcs", "reliance",
        "hdfc", "icici", "bharti", "airtel", "tata", "bajaj", "kotak",
        "maruti", "itc", "hindustan", "ultratech", "nestle", "asian paints",
        "axis", "sun pharma", "dr. reddy", "cipla", "hcl", "tech mahindra",
        "power grid", "ntpc", "ongc", "coal india", "bharat",
    ]
    for line in lines[:40]:
        clean = line.strip("*-–—|_ \t©®™")
        if len(clean) < 5 or len(clean) > 100:
            continue
        words = clean.split()
        if len(words) < 2:
            continue
        line_lower = clean.lower()
        if any(kw in line_lower for kw in company_keywords):
            if not any(w in line_lower for w in [
                "quarter ended", "financial results", "pursuant to",
                "regulation", "sebi", "stock exchange", "bse", "nse",
                "page ", "generated by", "finsight"
            ]):
                return clean
    return ""


def _extract_with_pdfplumber(raw_bytes: bytes, page_indices: list) -> str:
    try:
        import pdfplumber
        structured_text, currency = _build_structured_financials(raw_bytes, page_indices)

        if not structured_text.strip():
            raw_result = ""
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                for i in page_indices:
                    if i >= len(pdf.pages): continue
                    page = pdf.pages[i]
                    raw_text = page.extract_text() or ""
                    if raw_text.strip():
                        raw_result += f"\n--- PAGE {i+1} ---\n{raw_text}\n"
            structured_text = raw_result
            currency = _detect_currency_unit(raw_result)

        company_name = _extract_company_name(structured_text)
        company_line = f"[COMPANY NAME: {company_name}]\n" if company_name else ""

        header = (
            company_line +
            f"\n[DOCUMENT CURRENCY UNIT: {currency}]\n"
            f"[ALL NUMBERS ARE IN {currency} — DO NOT CHANGE THIS UNIT]\n\n"

            # ── CRITICAL: Anti-hallucination guard for Indian filings ──────────
            f"[CRITICAL EXTRACTION RULES FOR INDIAN QUARTERLY FILINGS]\n"
            f"[RULE A — AUDITOR NARRATIVE TRAP: Indian audit reports contain sentences like\n"
            f"  '247 subsidiaries reflect total revenues of Rs. X crore and net profit of Rs. Y crore'\n"
            f"  These X and Y numbers are SUBSIDIARY-ONLY figures cited by the auditor.\n"
            f"  They are NOT the consolidated P&L totals. NEVER use numbers from auditor review text.]\n"
            f"[RULE B — USE ONLY TABLE DATA: Extract revenue, PAT, EBITDA ONLY from rows in the\n"
            f"  'UNAUDITED CONSOLIDATED FINANCIAL RESULTS' table with columns like\n"
            f"  '31st Dec'25 | 30th Sep'25 | 31st Dec'24'. These are the real numbers.]\n"
            f"[RULE C — CONSOLIDATED FIRST: If both consolidated and standalone tables exist,\n"
            f"  use ONLY consolidated figures. Standalone values will be significantly lower.]\n"
            f"[RULE D — USE STATED RATIOS: For D/E ratio, Current Ratio, Interest Coverage —\n"
            f"  use the printed Ratios section values. Do not recalculate.]\n\n"

            f"[CONSOLIDATION: Use CONSOLIDATED figures only (labeled 'Unaudited Consolidated').\n"
            f"Standalone figures appear later in the document and must be IGNORED.]\n\n"
        )

        logger.info(f"pdfplumber extracted {len(structured_text):,} chars, currency={currency}")
        return header + structured_text

    except ImportError:
        logger.warning("pdfplumber not available")
        return ""
    except Exception as e:
        logger.warning(f"pdfplumber failed: {e}")
        return ""


def _extract_company_name(text: str) -> str:
    """Extract company name from the top of a BSE/NSE quarterly filing."""
    import re
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Look in first 30 lines for company name patterns
    skip_words = {"unaudited", "consolidated", "standalone", "financial", "results",
                  "quarter", "ended", "statement", "limited", "bse", "nse", "page",
                  "pursuant", "regulation", "sebi", "crore", "lakhs", "rs.", "inr"}
    for line in lines[:30]:
        # Lines in ALL CAPS or Title Case that look like company names
        clean = line.strip("*-–—|_ \t")
        if len(clean) < 5 or len(clean) > 80:
            continue
        words = clean.split()
        if len(words) < 2:
            continue
        # Must contain "Limited" or "Ltd" or "Corporation" or "Industries" etc.
        company_keywords = ["limited", "ltd", "corporation", "industries", "technologies",
                            "bank", "finance", "energy", "infosys", "wipro", "tcs",
                            "reliance", "hdfc", "icici", "bharti", "airtel", "tata"]
        line_lower = clean.lower()
        if any(kw in line_lower for kw in company_keywords):
            # Filter out lines that are mostly metadata
            if not any(w in line_lower for w in ["quarter ended", "financial results", "pursuant to"]):
                return clean
    return ""


def extract_financial_snippet(raw_bytes: bytes, max_chars: int = 60000) -> str:
    """
    Extract text from PDF and return it for AI analysis.
    Strategy:
      1. Select the right pages (consolidated P&L, ratios, segment) — up to page 20
      2. Run deterministic extractor to get verified numbers with source citations
      3. Extract structured text via pdfplumber (table-aware) with pypdf fallback
      4. Prepend VERIFIED DATA BLOCK (deterministic numbers) + PRINTED RATIOS
         so AI uses ground-truth numbers, not hallucinated ones
    """
    # Guard: reject FinSight reports
    try:
        import pdfplumber as _plumber
        with _plumber.open(io.BytesIO(raw_bytes)) as _chk:
            _sample = " ".join((_chk.pages[i].extract_text() or "") for i in range(min(2, len(_chk.pages))))
            if "finsight" in _sample.lower() and "institutional equity research" in _sample.lower():
                raise ValueError(
                    "This is a FinSight-generated report, not an original filing. "
                    "Please upload the original PDF from BSE (bseindia.com) or NSE (nseindia.com)."
                )
    except ValueError:
        raise
    except Exception:
        pass

    page_indices = _select_financial_pages(raw_bytes)
    if not page_indices:
        logger.warning("No financial pages selected — falling back to first 8 pages")
        page_indices = list(range(min(8, pypdf.PdfReader(io.BytesIO(raw_bytes)).pages.__len__())))

    # ── Also scan ALL pages for ratios (ratios section may be page 5-8, excluded by page filter) ──
    try:
        all_page_count = len(pypdf.PdfReader(io.BytesIO(raw_bytes)).pages)
        ratios_scan_pages = sorted(set(page_indices) | set(range(min(all_page_count, 20))))
    except Exception:
        ratios_scan_pages = page_indices

    # ── Step 1: Deterministic extraction — verified numbers with source citations ──
    try:
        det = _extract_deterministic(raw_bytes, ratios_scan_pages)
        verified_block = _build_verified_block(det)
        logger.info(f"Deterministic: pl_keys={list(det['pl'].keys())}, ratio_keys={list(det['ratios'].keys())}")
    except Exception as e:
        logger.warning(f"Deterministic extraction failed: {e}")
        verified_block = ""

    # ── Step 2: Extract full document text via pdfplumber ────────────────────
    text = _extract_with_pdfplumber(raw_bytes, page_indices)
    if not text.strip():
        logger.info("pdfplumber empty, falling back to pypdf")
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        text = ""
        for i in page_indices:
            pt = reader.pages[i].extract_text() or ""
            if pt.strip():
                text += f"\n--- PAGE {i+1} ---\n{pt}\n"

    # ── Step 3: Ratios cheat-sheet (scans wider page range than page_indices) ──
    ratios_hint = _extract_ratios_hint(raw_bytes, ratios_scan_pages)

    # ── Step 4: Assemble final prompt input ──────────────────────────────────
    # Order: VERIFIED BLOCK (ground truth) → RATIOS HINT → DOCUMENT TEXT
    # AI must use verified block numbers; document text provides context
    parts = []
    if verified_block:
        parts.append(verified_block)
    if ratios_hint:
        parts.append(ratios_hint)
    if text.strip():
        parts.append("\n━━━ FULL DOCUMENT TEXT (for context) ━━━\n" + text)
    combined = "\n\n".join(parts)

    is_partial = (
        "newspaper" in combined.lower() or
        "business standard" in combined.lower() or
        "extract of" in combined.lower() or
        len(combined) < 3000
    )
    if is_partial:
        combined = (
            "[SYSTEM NOTE: PARTIAL FILING DETECTED. "
            "Only write numbers explicitly visible. Mark unavailable fields as 'Not available'.\n\n"
            + combined
        )

    final = combined[:max_chars]
    logger.info(f"Final snippet: {len(final):,} chars (verified={len(verified_block)}, ratios={len(ratios_hint)}, text={len(text)})")
    return final


def _extract_ratios_hint(raw_bytes: bytes, page_indices: list) -> str:
    """
    Extract the printed Ratios table values and return as a pinned hint block.
    These values extract cleanly (no font encoding issues) and are critical
    to prevent AI from recalculating ratios incorrectly.
    """
    RATIO_ROWS = [
        ("Debt Service Coverage Ratio",   ["debt service coverage"]),
        ("Interest Service Coverage",     ["interest service coverage", "interest coverage ratio"]),
        ("Debt Equity Ratio",             ["debt equity ratio"]),
        ("Current Ratio",                 ["current ratio"]),
        ("Long-term Debt to Working Cap", ["long-term debt to working capital", "long term debt to working"]),
        ("Current Liability Ratio",       ["current liability ratio"]),
        ("Total Debts to Total Assets",   ["total debts to total assets", "total debt to total assets"]),
        ("Debtors Turnover",              ["debtors turnover"]),
        ("Inventory Turnover",            ["inventory turnover"]),
        ("Operating Margin (%)",          ["operating margin"]),
        ("Net Profit Margin (%)",         ["net profit margin"]),
    ]

    found = {}
    net_worth_val = ""

    try:
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        for page_idx in page_indices:
            if page_idx >= len(reader.pages):
                continue
            page_text = reader.pages[page_idx].extract_text() or ""
            tl = page_text.lower()

            # Only process pages that have a ratios section
            if "ratios" not in tl:
                continue
            if "debt equity" not in tl and "operating margin" not in tl:
                continue

            lines = page_text.split("\n")
            for line in lines:
                ll = line.lower().strip()

                # Net worth
                if "net worth" in ll and ("including" in ll or "retained" in ll):
                    nums = re.findall(r"[\d,]+", line)
                    nums = [n.replace(",","") for n in nums if len(n.replace(",","")) >= 4]
                    if nums and not net_worth_val:
                        net_worth_val = nums[0]

                # EPS
                if "basic (in" in ll or "basic (in ₹" in ll:
                    nums = re.findall(r"\d+\.\d+|\d+", line)
                    nums = [n for n in nums if 0 < float(n) < 1000]
                    if nums:
                        found["EPS Basic (₹)"] = nums[0]

                # Ratios
                for label, patterns in RATIO_ROWS:
                    if label in found:
                        continue
                    if any(p in ll for p in patterns):
                        nums = re.findall(r"[-]?\d+\.\d+|[-]?\d+", line)
                        nums = [n for n in nums if n not in ("0", "-0")]
                        if nums:
                            found[label] = nums[0]
                        break

    except Exception as e:
        logger.warning(f"Ratios hint extraction failed: {e}")
        return ""

    if not found:
        return ""

    lines = ["[PRINTED RATIOS FROM FILING — USE THESE EXACT VALUES, DO NOT RECALCULATE]"]
    for label, val in found.items():
        lines.append(f"  {label}: {val}")
    if net_worth_val:
        lines.append(f"  Net Worth (₹ Cr): {net_worth_val}")
    lines.append("[END RATIOS]")
    return "\n".join(lines)


def extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        reader    = pypdf.PdfReader(io.BytesIO(raw_bytes))
        num_pages = len(reader.pages)

        sample_text = ""
        for page in reader.pages[:10]:
            sample_text += page.extract_text() or ""
        if len(sample_text.strip()) < 100:
            raise ValueError(
                "This PDF appears to be scanned/image-based — no selectable text found. "
                "Please download the digital/searchable version from BSE or NSE.")

        logger.info(f"PDF validated: {num_pages} pages")
        return extract_financial_snippet(raw_bytes)
    except ValueError: raise
    except Exception as e:
        logger.error(f"PDF read error: {e}")
        raise ValueError(f"Could not read this PDF: {str(e)}")


# ─── JSON REPAIR ─────────────────────────────────────────────────────────────
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


# ─── AI PROMPTS ──────────────────────────────────────────────────────────────

def build_prompt(text: str, max_doc_chars: int = 44000) -> str:
    snippet = text[:max_doc_chars]
    logger.info(f"build_prompt: {len(snippet):,} chars")
    return f"""You are a senior equity research analyst at an institutional fund.
Analyze the financial data below and return ONLY one valid JSON object.
Write like a Goldman Sachs research note: specific, opinionated, number-driven.

━━━ VERIFIED DATA BLOCK (if present) ━━━
The document may begin with a VERIFIED FINANCIAL DATA block enclosed in ╔══╗ borders.
These numbers were deterministically extracted from the filing tables with source citations.
TREAT THEM AS ABSOLUTE GROUND TRUTH. Do not override them with numbers from the document text.

━━━ DOCUMENT RULES ━━━
RULE 1 — AUDITOR TRAP: Text like "subsidiaries reflect revenues of Rs. X crore" = audit scope note.
These are NOT consolidated results. Only use numbers from the P&L table rows.

RULE 2 — PRINTED RATIOS: If [PRINTED RATIOS FROM FILING] block exists, use those exact values.
Never recalculate D/E, Current Ratio, Interest Coverage, Operating Margin, Net Profit Margin.

RULE 3 — CONSOLIDATED ONLY: Ignore standalone tables.

RULE 4 — CASH FLOW:
- Quarterly PDF (Q1/Q2/Q3): NO cash flow statement included. Set ALL CF fields to
  "Not available — quarterly filing". Cash Flow score = 9. NEVER fabricate OCF figures.
- Annual report or Screener.in data: analyse cash flow figures actually present.
  Compute OCF/PAT ratio. State earnings quality (Strong if OCF>PAT, Moderate if ≈PAT, Weak if <PAT).

RULE 5 — HALLUCINATION BAN (CRITICAL):
If a number is NOT explicitly in the document or verified block → write "Not available in this filing".
NEVER invent, estimate, or calculate values not shown. One wrong number destroys user trust.

RULE 6 — SPECIFICITY (MOST IMPORTANT FOR QUALITY):
Every analysis field MUST cite actual numbers. Vague commentary is waste.
❌ REJECTED: "Revenue grew strongly reflecting robust demand across segments"
✅ ACCEPTED: "Revenue ₹2,69,496 Cr, up 10.5% YoY from ₹2,43,865 Cr — Jio +17%, Retail +8%"
❌ REJECTED: "Company has maintained strong profitability metrics"
✅ ACCEPTED: "Net margin 6.9% (₹18,645 Cr PAT on ₹2,69,496 Cr revenue), expanded 140bps YoY"

━━━ SCORING ━━━
Profitability(20): ROE>20%+Margin>15%=20|12-20%=14|else=7
Growth(15): Rev>15%+PAT>20%=15|Rev8-15%+PAT10-20%=10|else=4
BalanceSheet(15): D/E<0.5=15|0.5-1.0=11|1.0-1.5=7|>1.5=3
Liquidity(10): CR>2=10|1.5-2=8|1-1.5=5|<1=2
CashFlow(15): OCF>PAT=15|OCF≈PAT=10|OCF<PAT=4|NotAvailable=9
Governance(15): Clean+LowPledging=15|MinorIssues=9|MajorConcerns=3
Industry(10): MarketLeader=10|Strong#2-3=7|Average=4|Lagging=2
health_label: >=80=Excellent|65-79=Good|45-64=Fair|25-44=Poor|<25=Critical
investment_label: Strong Buy/Buy/Hold/Reduce/Avoid

━━━ WRITING STYLE ━━━
executive_summary: 5 sentences — (1) top-line revenue+PAT with figures (2) biggest positive with figures (3) biggest concern with figures (4) balance sheet/CF status (5) 1-2 quarter outlook
investor_verdict: 2 sentences — lead with rating + core reason, end with key risk
reasoning in breakdown: must cite exact numbers justifying the score
highlights: each starts with a specific metric e.g. "PAT up 38.7% YoY to ₹18,645 Cr"
risks: concrete, evidence-based — not "market risk" or "competition"
investor_faq: 3-4 sentences each, number-heavy, directly answer the question
key_monitorables: specific metrics with thresholds, not generic watchpoints

Return ONLY this JSON (all fields required, no nulls, no markdown fences):
{{
  "company_name": "",
  "statement_type": "Quarterly + Annual (Screener.in) or Quarterly Results or Annual Report",
  "period": "e.g. Q3 FY26 (Dec 2025) + FY2025 Annual — cover both",
  "currency": "e.g. INR Crore",
  "health_score": 0,
  "health_label": "",
  "health_score_breakdown": {{
    "total": 0,
    "components": [
      {{"category":"Profitability","weight":20,"score":0,"max":20,"rating":"Strong/Average/Weak","reasoning":"Cite actual margin % and ROE % with figures"}},
      {{"category":"Growth","weight":15,"score":0,"max":15,"rating":"Strong/Average/Weak","reasoning":"Revenue % YoY and PAT % YoY with actual figures"}},
      {{"category":"Balance Sheet","weight":15,"score":0,"max":15,"rating":"Strong/Average/Weak","reasoning":"D/E ratio, net worth, total debt figures"}},
      {{"category":"Liquidity","weight":10,"score":0,"max":10,"rating":"Strong/Average/Weak","reasoning":"Current ratio and cash context with figures"}},
      {{"category":"Cash Flow","weight":15,"score":0,"max":15,"rating":"Strong/Average/Weak","reasoning":"OCF/PAT ratio if available, or clearly state quarterly limitation"}},
      {{"category":"Governance & Risk","weight":15,"score":0,"max":15,"rating":"Strong/Average/Weak","reasoning":"Audit opinion, promoter pledging, related party concerns"}},
      {{"category":"Industry Position","weight":10,"score":0,"max":10,"rating":"Strong/Average/Weak","reasoning":"Market share, moat, competitive position vs named peers"}}
    ]
  }},
  "headline": "One punchy line ≤15 words with the single most important number from this result",
  "executive_summary": "5-6 sentences covering BOTH latest quarter AND latest full year: (1) Latest quarter top-line with exact numbers (2) Full year revenue+PAT with figures (3) Key positive driver (4) Key concern with figures (5) Cash flow quality from annual data (6) Forward outlook",
  "investment_label": "",
  "investor_verdict": "2 sentences: rating + core rationale with numbers + single biggest risk",
  "for_long_term_investors": "3-4 sentences: compounding thesis, 2-3 year catalysts, entry context with specifics",
  "for_short_term_traders": "3-4 sentences: near-term triggers, momentum signals, what would flip the thesis",
  "bottom_line": "One sentence conviction statement",
  "key_metrics": [
    {{"label":"Revenue","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":"One specific line on what drove the change"}},
    {{"label":"Net Profit","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"EBITDA Margin","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"ROE","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"Debt to Equity","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"Operating Cash Flow","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}}
  ],
  "cash_flow_deep_dive": {{
    "operating_cf": "Exact figure with period, or 'Not available — quarterly filing'",
    "investing_cf": "Exact figure or not available",
    "financing_cf": "Exact figure or not available",
    "free_cash_flow": "OCF minus Capex or not available",
    "capex": "Exact figure or not available",
    "cash_conversion_quality": "Strong (OCF 1.3x PAT) / Moderate / Weak — with actual ratio; or 'Not available — quarterly filing does not include cash flow statement'",
    "ocf_vs_pat_insight": "Earnings quality: is cash profit higher than accounting profit? Use actual numbers. Or state quarterly limitation."
  }},
  "balance_sheet_deep_dive": {{
    "asset_quality": "Asset base with figures — fixed assets, investments, working capital quality",
    "debt_profile": "Total debt figure, LT vs ST mix if available, cost of debt if disclosed",
    "working_capital_insight": "Debtor days, inventory days if derivable from data",
    "total_debt": "",
    "net_worth": "",
    "debt_to_equity": "",
    "interest_coverage": "",
    "debt_comfort_level": "Comfortable/Elevated/Stressed — with D/E and ICR rationale"
  }},
  "growth_quality": {{
    "revenue_growth_context": "WHY did revenue grow/fall — which segments, what magnitude? Cite figures.",
    "profit_growth_context": "PAT growth drivers — margin expansion, lower tax, one-offs? Cite figures.",
    "margin_trend": "Operating margin expansion/contraction vs last year in exact bps",
    "growth_outlook": "Next 2-4 quarters based on guidance or sector momentum",
    "catalysts": ["Specific catalyst 1 with expected magnitude", "Specific catalyst 2"],
    "headwinds": ["Specific headwind 1 with context and magnitude", "Specific headwind 2"]
  }},
  "industry_context": {{
    "sector_tailwinds": ["Tailwind 1 specific to this sector/company", "Tailwind 2"],
    "sector_headwinds": ["Headwind 1", "Headwind 2"],
    "competitive_position": "Market position vs named peers — leader, challenger, or niche?",
    "peer_benchmarks": "Margins/growth/D/E vs named peers in same sector",
    "regulatory_environment": "Relevant regulatory tailwinds or headwinds"
  }},
  "red_flags": ["Specific red flag with evidence from filing", "Specific red flag 2 — not generic"],
  "strengths_and_moats": ["Specific moat — e.g. 430M subscriber base, pricing power, brand", "Specific moat 2"],
  "investor_faq": [
    {{"question":"Is this company a good investment right now?","answer":"3-4 sentences: investment case with numbers, valuation context, key risk."}},
    {{"question":"What is the biggest risk to monitor?","answer":"3-4 sentences: specific, evidence-based, not generic."}},
    {{"question":"How sustainable is the current growth rate?","answer":"3-4 sentences: segment drivers, market opportunity, structural constraints."}}
  ],
  "key_monitorables": [
    "Specific metric with threshold — e.g. Watch Jio ARPU: needs to sustain above ₹195 to justify Digital valuation",
    "Monitorable 2 with context and threshold",
    "Monitorable 3"
  ],
  "profitability": {{
    "analysis": "3-4 sentences: margin quality, what drives them, sustainability, trend vs historical and peers",
    "net_margin_current": "",
    "ebitda_margin_current": "",
    "roe": "",
    "roa": ""
  }},
  "liquidity": {{
    "analysis": "2-3 sentences: can company meet near-term obligations? Any stress signals?",
    "current_ratio": "",
    "quick_ratio": "",
    "cash_position": "",
    "operating_cash_flow": "",
    "free_cash_flow": ""
  }},
  "highlights": [
    "Number-led — e.g. PAT up 38.7% YoY to ₹18,645 Cr, strongest quarter in last 6",
    "Number-led highlight 2",
    "Number-led highlight 3"
  ],
  "risks": [
    "Specific risk with magnitude — e.g. O2C under pressure: GRMs at $8.4/bbl vs $10.1/bbl YoY, -17%",
    "Specific risk 2 with evidence",
    "Specific risk 3"
  ],
  "what_to_watch": [
    "Specific trigger for next quarter with clear threshold",
    "What to watch 2",
    "What to watch 3"
  ]
}}

FINANCIAL DATA:
{snippet}
"""

def build_lean_prompt(text: str, max_doc_chars: int = 18000) -> str:
    snippet = text[:max_doc_chars]
    return f"""Senior equity research analyst. Return ONLY valid JSON. Every field needs actual numbers from the data.

RULES:
1. VERIFIED BLOCK: If ╔══╗ bordered block present at top — use those numbers as ground truth.
2. AUDITOR TRAP: "subsidiaries reflect revenues Rs. X crore" = audit note. Ignore. Not consolidated results.
3. HALLUCINATION BAN: Number not in data → "Not available in this filing". Never invent or estimate.
4. SPECIFICITY: Every sentence needs actual figures. "Revenue ₹X Cr, up Y% YoY" not "revenue grew."
5. CASH FLOW QUARTERLY: No CF in Q1/Q2/Q3 filings. All CF fields = "Not available — quarterly filing". CF score = 9.
6. CASH FLOW ANNUAL/SCREENER: If annual data present, analyse OCF, FCF. Compute OCF/PAT ratio.
7. CONSOLIDATED ONLY. USE PRINTED RATIOS exactly — never recalculate.

SCORING: Profitability(20):ROE>20%+Margin>15%=20|12-20%=14|else=7 | Growth(15):Rev>15%+PAT>20%=15|8-15%=10|else=4 | BalSheet(15):D/E<0.5=15|0.5-1.0=11|1.0-1.5=7|>1.5=3 | Liquidity(10):CR>2=10|1.5-2=8|1-1.5=5|<1=2 | CF(15):OCF>PAT=15|≈PAT=10|<PAT=4|NA=9 | Gov(15):Clean=15|Minor=9|Major=3 | Industry(10):Leader=10|Strong=7|Avg=4|Lag=2
health_label: >=80=Excellent|65-79=Good|45-64=Fair|25-44=Poor|<25=Critical
investment_label: Strong Buy/Buy/Hold/Reduce/Avoid

Return ONLY this JSON:
{{
  "company_name":"","statement_type":"","period":"","currency":"","health_score":0,"health_label":"",
  "health_score_breakdown":{{"total":0,"components":[
    {{"category":"Profitability","weight":20,"score":0,"max":20,"rating":"","reasoning":"margin % + ROE % with figures"}},
    {{"category":"Growth","weight":15,"score":0,"max":15,"rating":"","reasoning":"rev % + PAT % YoY with figures"}},
    {{"category":"Balance Sheet","weight":15,"score":0,"max":15,"rating":"","reasoning":"D/E, net worth, debt figures"}},
    {{"category":"Liquidity","weight":10,"score":0,"max":10,"rating":"","reasoning":"current ratio + cash context"}},
    {{"category":"Cash Flow","weight":15,"score":0,"max":15,"rating":"","reasoning":"OCF/PAT ratio or quarterly limitation"}},
    {{"category":"Governance & Risk","weight":15,"score":0,"max":15,"rating":"","reasoning":"audit, pledging, red flags"}},
    {{"category":"Industry Position","weight":10,"score":0,"max":10,"rating":"","reasoning":"market position + moat vs peers"}}
  ]}},
  "headline":"Single most important number from this result in ≤15 words",
  "executive_summary":"5 sentences: (1)top-line with exact numbers (2)biggest positive driver (3)key concern (4)balance sheet/CF (5)outlook",
  "investment_label":"","investor_verdict":"2 sentences: rating+rationale with numbers + key risk",
  "for_long_term_investors":"3-4 sentences with specific catalysts and entry context",
  "for_short_term_traders":"3-4 sentences with near-term triggers and momentum signals",
  "bottom_line":"One conviction sentence",
  "key_metrics":[
    {{"label":"Revenue","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":"What drove the change"}},
    {{"label":"Net Profit","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"EBITDA Margin","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"ROE","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"Debt to Equity","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}},
    {{"label":"Operating Cash Flow","current":"","previous":"","change":"","trend":"up/down/stable","signal":"Positive/Negative/Neutral","comment":""}}
  ],
  "cash_flow_deep_dive":{{"operating_cf":"Figure or not available","investing_cf":"","financing_cf":"","free_cash_flow":"OCF-Capex or not available","capex":"","cash_conversion_quality":"Strong(OCF Xx PAT)/Moderate/Weak with ratio; or not available reason","ocf_vs_pat_insight":"Earnings quality analysis with numbers, or quarterly limitation"}},
  "balance_sheet_deep_dive":{{"asset_quality":"Asset base with figures","debt_profile":"Total debt, LT vs ST","working_capital_insight":"Debtor/inventory days if available","total_debt":"","net_worth":"","debt_to_equity":"","interest_coverage":"","debt_comfort_level":"Comfortable/Elevated/Stressed with D/E+ICR rationale"}},
  "growth_quality":{{"revenue_growth_context":"WHY revenue changed — segments and figures","profit_growth_context":"PAT drivers with numbers","margin_trend":"Exact bps expansion/contraction","growth_outlook":"Next 2-4 quarters","catalysts":["Catalyst 1 with magnitude","Catalyst 2"],"headwinds":["Headwind 1 with context","Headwind 2"]}},
  "industry_context":{{"sector_tailwinds":["Tailwind 1","Tailwind 2"],"sector_headwinds":["Headwind 1","Headwind 2"],"competitive_position":"Position vs named peers","peer_benchmarks":"Margins/growth/D/E vs named peers","regulatory_environment":"Relevant factors"}},
  "red_flags":["Red flag with evidence from filing","Red flag 2 specific not generic"],
  "strengths_and_moats":["Specific moat 1 — scale/brand/network/pricing power","Specific moat 2"],
  "investor_faq":[
    {{"question":"Is this company a good investment right now?","answer":"3-4 sentences: investment case + numbers + valuation + risk"}},
    {{"question":"What is the biggest risk to monitor?","answer":"3-4 sentences: specific risk with evidence"}},
    {{"question":"How sustainable is the current growth rate?","answer":"3-4 sentences: segments + opportunity + constraints"}}
  ],
  "key_monitorables":["Specific metric with threshold — e.g. Watch ARPU sustain above ₹195","Monitorable 2 with threshold","Monitorable 3"],
  "profitability":{{"analysis":"3-4 sentences on margin quality, drivers, sustainability, trend","net_margin_current":"","ebitda_margin_current":"","roe":"","roa":""}},
  "liquidity":{{"analysis":"2-3 sentences with specific ratios and liquidity assessment","current_ratio":"","quick_ratio":"","cash_position":"","operating_cash_flow":"","free_cash_flow":""}},
  "highlights":["Number-led highlight 1 — e.g. PAT up 38.7% YoY to ₹18,645 Cr","Highlight 2","Highlight 3"],
  "risks":["Specific risk with magnitude and evidence","Risk 2","Risk 3"],
  "what_to_watch":["Specific trigger with threshold for next quarter","Watch 2","Watch 3"]
}}

FINANCIAL DATA:
{snippet}
"""

# ─── AI PROVIDER FUNCTIONS ───────────────────────────────────────────────────

def _sync_gemini(text: str) -> dict:
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not configured")

    models = [
        ("gemini-2.0-flash",               44000, False),
        ("gemini-2.0-flash-lite",          44000, False),
        ("gemini-2.5-flash-preview-04-17", 44000, False),
        ("gemini-2.0-flash-exp",           20000, True),
    ]

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            logger.info("Gemini %s: sending %d chars", model, len(prompt))
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 16384},
                },
                timeout=120,
            )
            logger.info("Gemini %s: HTTP %d", model, resp.status_code)

            if resp.status_code == 200:
                body = resp.json()
                candidates = body.get("candidates", [])
                if candidates:
                    raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    if raw:
                        return safe_parse_json(raw)
                    logger.warning("Gemini %s: empty response", model)
                else:
                    last_error = f"No candidates: {body.get('promptFeedback', '')}"
                continue

            if resp.status_code == 429:
                last_error = "Rate limited (429)"
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            logger.warning("Gemini %s: %s", model, last_error)

        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
            continue
        except Exception as e:
            last_error = str(e)[:200]
            continue

    raise Exception(f"All Gemini models failed. Last: {last_error}")


def _sync_groq(text: str) -> dict:
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY not configured")

    models = [
        ("llama-3.3-70b-versatile",               20000, False),
        ("llama-3.1-8b-instant",                  14000, True),
        ("llama3-groq-70b-8192-tool-use-preview", 14000, True),
        ("llama3-groq-8b-8192-tool-use-preview",  14000, True),
    ]

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            logger.info("Groq %s: sending %d chars", model, len(prompt))
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 16384,
                    "temperature": 0.1,
                },
                timeout=120,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                if raw:
                    return safe_parse_json(raw)
                continue
            if resp.status_code == 429:
                last_error = "Rate limited (429)"
                continue
            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
        except Exception as e:
            last_error = str(e)[:200]

    raise Exception(f"All Groq models failed. Last: {last_error}")


def _sync_together(text: str) -> dict:
    api_key = os.getenv("TOGETHER_API_KEY", "")
    if not api_key:
        raise Exception("TOGETHER_API_KEY not configured")

    models = [
        ("meta-llama/Llama-3.3-70B-Instruct-Turbo",      44000, False),
        ("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", 44000, False),
        ("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",  20000, True),
    ]

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            resp = requests.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 16384, "temperature": 0.1},
                timeout=120,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                if raw:
                    return safe_parse_json(raw)
            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
        except Exception as e:
            last_error = str(e)[:200]

    raise Exception(f"All Together models failed. Last: {last_error}")


def _sync_openrouter(text: str) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise Exception("OPENROUTER_API_KEY not configured")

    models = [
        ("meta-llama/llama-3.3-70b-instruct", 44000, False),
        ("meta-llama/llama-3.1-70b-instruct", 44000, False),
        ("google/gemma-2-27b-it",             20000, True),
    ]

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://finsight-vert.vercel.app", "X-Title": "FinSight"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 16384, "temperature": 0.1},
                timeout=120,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                if raw:
                    return safe_parse_json(raw)
            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
        except Exception as e:
            last_error = str(e)[:200]

    raise Exception(f"All OpenRouter models failed. Last: {last_error}")


def _sync_cloudflare(text: str) -> dict:
    cf_account = os.getenv("CF_ACCOUNT_ID", "")
    cf_token   = os.getenv("CF_API_TOKEN", "")
    if not cf_account or not cf_token:
        raise Exception("CF_ACCOUNT_ID or CF_API_TOKEN not configured")

    models = [
        ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", 12000, False),
        ("@cf/meta/llama-3.1-8b-instruct-fast",       10000, True),
    ]
    headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"}

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run/{model}"
            resp = requests.post(
                url, headers=headers,
                json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 16384, "temperature": 0.1},
                timeout=120,
            )
            if resp.status_code == 200:
                body = resp.json()
                if body.get("success"):
                    raw = body.get("result", {}).get("response", "")
                    if raw:
                        return safe_parse_json(raw)
            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
        except Exception as e:
            last_error = str(e)[:200]

    raise Exception(f"All Cloudflare models failed. Last: {last_error}")


# ─── MAIN ANALYSIS ORCHESTRATOR ──────────────────────────────────────────────
async def run_analysis(text: str) -> dict:
    if not text or len(text.strip()) < 100:
        raise Exception("PDF extraction returned insufficient text.")

    full_text = text.strip()

    financial_keywords = ["revenue", "profit", "income", "assets", "crore", "lakh",
                          "eps", "ebitda", "loss", "balance sheet", "borrowing", "equity"]
    found_kw = [kw for kw in financial_keywords if kw.lower() in full_text.lower()]
    if len(found_kw) < 2:
        raise Exception(
            f"Extracted text does not appear to contain financial data "
            f"(found only: {found_kw}). Preview: {full_text[:200]}"
        )

    logger.info(f"Analysis starting — text: {len(full_text):,} chars")

    loop   = asyncio.get_event_loop()
    errors = []

    providers = [
        ("Gemini",      _sync_gemini,      GEMINI_API_KEY),
        ("Groq",        _sync_groq,        GROQ_API_KEY),
        ("Cloudflare",  _sync_cloudflare,  os.getenv("CF_API_TOKEN", "")),
        ("Together",    _sync_together,    os.getenv("TOGETHER_API_KEY", "")),
        ("OpenRouter",  _sync_openrouter,  os.getenv("OPENROUTER_API_KEY", "")),
    ]

    for provider_name, func, api_key in providers:
        if not api_key:
            logger.info(f"Skipping {provider_name} (no API key)")
            continue
        try:
            logger.info(f"Trying {provider_name} with {len(full_text):,} chars...")
            result = await loop.run_in_executor(executor, func, full_text)
            logger.info(f"{provider_name} succeeded!")
            return result
        except Exception as e:
            error_msg = str(e)[:200]
            logger.warning(f"{provider_name} failed: {error_msg}")
            errors.append(f"{provider_name}: {error_msg}")

    error_summary = " | ".join(errors) if errors else "No API keys configured"
    raise Exception(f"All AI providers failed. {error_summary}")


# ─── FMP HELPERS ─────────────────────────────────────────────────────────────
_fmp_cache: dict = {}
_FMP_CACHE_TTL   = 300

def _fmp_cached(key: str):
    entry = _fmp_cache.get(key)
    if entry:
        ts, data = entry
        if (datetime.utcnow() - ts).total_seconds() < _FMP_CACHE_TTL:
            return data
    return None

def _fmp_store(key: str, data):
    _fmp_cache[key] = (datetime.utcnow(), data)
    return data

def _fmp_symbol(symbol: str) -> str:
    sym = symbol.upper().strip()
    if sym.startswith("BSE_"):
        return sym.replace("BSE_", "") + ".BO"
    return sym + ".NS"

def _safe(val, decimals=2):
    if val is None: return None
    try: return round(float(val), decimals)
    except: return None

def _fmt_cr(val) -> str:
    try:
        v = float(val)
        return f"₹{v/1e7:,.2f} Cr" if abs(v) >= 1e7 else f"₹{v:,.0f}"
    except: return str(val) if val else "N/A"


async def _fmp_get(endpoint: str, params: dict = None) -> dict:
    if not FMP_API_KEY:
        raise Exception("FMP_API_KEY not configured")
    p = {"apikey": FMP_API_KEY, **(params or {})}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{FMP_BASE}{endpoint}", params=p)
    if r.status_code != 200:
        raise Exception(f"FMP API error {r.status_code}: {r.text[:200]}")
    data = r.json()
    if isinstance(data, dict) and "Error Message" in data:
        raise Exception(f"FMP error: {data['Error Message']}")
    return data


async def get_fmp_quote(symbol: str) -> dict:
    sym = symbol.upper().strip()
    cached = _fmp_cached(f"quote:{sym}")
    if cached:
        return cached

    fmp_sym = _fmp_symbol(sym)
    logger.info(f"FMP fetching quote for {fmp_sym}")

    try:
        quote_data, profile_data, ratio_data = await asyncio.gather(
            _fmp_get(f"/v3/quote/{fmp_sym}"),
            _fmp_get(f"/v3/profile/{fmp_sym}"),
            _fmp_get(f"/v3/ratios-ttm/{fmp_sym}"),
            return_exceptions=True
        )

        q = quote_data[0]   if isinstance(quote_data,  list) and quote_data  else {}
        p = profile_data[0] if isinstance(profile_data,list) and profile_data else {}
        r = ratio_data[0]   if isinstance(ratio_data,  list) and ratio_data  else {}

        price      = _safe(q.get("price"))
        prev_close = _safe(q.get("previousClose"))
        change     = _safe(q.get("change"))
        change_pct = _safe(q.get("changesPercentage"))
        market_cap = q.get("marketCap")

        w52h = _safe(q.get("yearHigh"))
        w52l = _safe(q.get("yearLow"))
        w52pos = None
        if w52h and w52l and price and (w52h - w52l) > 0:
            w52pos = round(((price - w52l) / (w52h - w52l)) * 100, 1)

        result = {
            "symbol":        sym,
            "fmp_symbol":    fmp_sym,
            "exchange":      p.get("exchangeShortName", "NSE"),
            "company_name":  q.get("name") or p.get("companyName", sym),
            "sector":        p.get("sector"),
            "industry":      p.get("industry"),
            "currency":      p.get("currency", "INR"),
            "description":   p.get("description", "")[:300] if p.get("description") else None,
            "price":          price,
            "prev_close":     prev_close,
            "open":           _safe(q.get("open")),
            "day_high":       _safe(q.get("dayHigh")),
            "day_low":        _safe(q.get("dayLow")),
            "day_change":     change,
            "day_change_pct": change_pct,
            "week_52_high":   w52h,
            "week_52_low":    w52l,
            "week_52_position_pct": w52pos,
            "volume":         q.get("volume"),
            "avg_volume":     q.get("avgVolume"),
            "market_cap":     market_cap,
            "market_cap_fmt": _fmt_cr(market_cap),
            "pe_ratio":       _safe(q.get("pe")),
            "eps":            _safe(q.get("eps")),
            "pb_ratio":       _safe(r.get("priceToBookRatioTTM")),
            "ps_ratio":       _safe(r.get("priceToSalesRatioTTM")),
            "ev_ebitda":      _safe(r.get("enterpriseValueMultipleTTM")),
            "beta":           _safe(p.get("beta")),
            "shares_outstanding": p.get("sharesOutstanding"),
            "dividend_yield_pct": _safe(r.get("dividendYieldPercentageTTM")),
            "dividend_per_share": _safe(r.get("dividendPerShareTTM")),
            "gross_margin_pct":     _safe(r.get("grossProfitMarginTTM") and r["grossProfitMarginTTM"] * 100),
            "operating_margin_pct": _safe(r.get("operatingProfitMarginTTM") and r["operatingProfitMarginTTM"] * 100),
            "net_margin_pct":       _safe(r.get("netProfitMarginTTM") and r["netProfitMarginTTM"] * 100),
            "roe_pct":              _safe(r.get("returnOnEquityTTM") and r["returnOnEquityTTM"] * 100),
            "roa_pct":              _safe(r.get("returnOnAssetsTTM") and r["returnOnAssetsTTM"] * 100),
            "roic_pct":             _safe(r.get("returnOnCapitalEmployedTTM") and r["returnOnCapitalEmployedTTM"] * 100),
            "debt_to_equity":   _safe(r.get("debtEquityRatioTTM")),
            "current_ratio":    _safe(r.get("currentRatioTTM")),
            "quick_ratio":      _safe(r.get("quickRatioTTM")),
            "interest_coverage":_safe(r.get("interestCoverageTTM")),
            "asset_turnover":   _safe(r.get("assetTurnoverTTM")),
            "inventory_turnover":_safe(r.get("inventoryTurnoverTTM")),
            "data_source": "Financial Modeling Prep (FMP)",
            "fetched_at":  datetime.utcnow().isoformat() + "Z",
        }

        return _fmp_store(f"quote:{sym}", result)

    except Exception as e:
        raise Exception(f"FMP quote failed for {sym}: {str(e)}")


# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    company_count = await companies_col.count_documents({})
    return {"status": "ok", "time": datetime.utcnow().isoformat(),
            "gemini":      bool(GEMINI_API_KEY),
            "groq":        bool(GROQ_API_KEY),
            "cloudflare":  bool(os.getenv("CF_API_TOKEN")),
            "openrouter":  bool(os.getenv("OPENROUTER_API_KEY")),
            "fmp":         bool(FMP_API_KEY),
            "companies_in_db": company_count}


@app.get("/api/quote/{symbol}")
async def get_quote(symbol: str):
    sym = symbol.upper().strip()
    if not sym:
        raise HTTPException(400, "Symbol is required")
    if not FMP_API_KEY:
        raise HTTPException(503, "FMP_API_KEY not configured on server")
    try:
        return await get_fmp_quote(sym)
    except Exception as e:
        raise HTTPException(404, str(e))


@app.get("/api/quote/{symbol}/history")
async def get_quote_history(symbol: str, period: str = "1y"):
    if not FMP_API_KEY:
        raise HTTPException(503, "FMP_API_KEY not configured on server")

    sym     = symbol.upper().strip()
    fmp_sym = _fmp_symbol(sym)
    period_map = {"1m": 30, "3m": 90, "6m": 180, "1y": 365, "3y": 1095, "5y": 1825}
    if period not in period_map:
        raise HTTPException(400, f"Invalid period. Valid: {list(period_map.keys())}")

    cache_key = f"history:{sym}:{period}"
    cached = _fmp_cached(cache_key)
    if cached:
        return cached

    try:
        data = await _fmp_get(f"/v3/historical-price-full/{fmp_sym}", {"timeseries": period_map[period]})
        records = [{"date": d.get("date"), "open": _safe(d.get("open")), "high": _safe(d.get("high")),
                    "low": _safe(d.get("low")), "close": _safe(d.get("close")), "volume": d.get("volume")}
                   for d in (data.get("historical") or [])]
        result = {"symbol": sym, "fmp_symbol": fmp_sym, "period": period, "count": len(records),
                  "data": records, "fetched_at": datetime.utcnow().isoformat() + "Z"}
        return _fmp_store(cache_key, result)
    except Exception as e:
        raise HTTPException(404, str(e))


@app.get("/api/quote/{symbol}/financials")
async def get_financials(symbol: str):
    if not FMP_API_KEY:
        raise HTTPException(503, "FMP_API_KEY not configured on server")

    sym     = symbol.upper().strip()
    fmp_sym = _fmp_symbol(sym)
    cache_key = f"financials:{sym}"
    cached = _fmp_cached(cache_key)
    if cached:
        return cached

    try:
        income, balance, cashflow = await asyncio.gather(
            _fmp_get(f"/v3/income-statement/{fmp_sym}",        {"limit": 4}),
            _fmp_get(f"/v3/balance-sheet-statement/{fmp_sym}", {"limit": 4}),
            _fmp_get(f"/v3/cash-flow-statement/{fmp_sym}",     {"limit": 4}),
        )
        result = {"symbol": sym, "fmp_symbol": fmp_sym, "source": "Financial Modeling Prep",
                  "income_statement": income or [], "balance_sheet": balance or [],
                  "cash_flow": cashflow or [], "fetched_at": datetime.utcnow().isoformat() + "Z"}
        return _fmp_store(cache_key, result)
    except Exception as e:
        raise HTTPException(404, str(e))


@app.post("/api/quotes/batch")
async def get_batch_quotes(body: dict):
    symbols: list = body.get("symbols", [])
    if not symbols or not isinstance(symbols, list):
        raise HTTPException(400, 'Body must be { "symbols": ["SYM1", ...] }')
    if len(symbols) > 20:
        raise HTTPException(400, "Maximum 20 symbols per batch")
    if not FMP_API_KEY:
        raise HTTPException(503, "FMP_API_KEY not configured on server")

    results = {}
    for sym in symbols:
        s = sym.upper().strip()
        try:
            results[s] = await get_fmp_quote(s)
        except Exception as e:
            results[s] = {"symbol": s, "error": str(e), "status": "failed"}

    return {"count": len(results), "results": results, "fetched_at": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/market/movers")
async def get_market_movers():
    if not FMP_API_KEY:
        raise HTTPException(503, "FMP_API_KEY not configured on server")
    cached = _fmp_cached("market:movers")
    if cached:
        return cached

    NIFTY50 = [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
        "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","SUNPHARMA",
        "TITAN","ULTRACEMCO","BAJFINANCE","WIPRO","NESTLEIND","HCLTECH","TECHM",
        "POWERGRID","NTPC","TATAMOTORS","ADANIENT","JSWSTEEL","GRASIM","TATASTEEL",
        "ADANIPORTS","ONGC","BAJAJFINSV","BRITANNIA","EICHERMOT","BPCL","COALINDIA",
        "DIVISLAB","DRREDDY","CIPLA","APOLLOHOSP","HEROMOTOCO","INDUSINDBK","MM",
        "SHREECEM","UPL","TATACONSUM","BAJAJAUTO","HINDALCO","SBILIFE","HDFCLIFE"
    ]

    async def _safe_quote(sym):
        try: return await get_fmp_quote(sym)
        except: return None

    results = await asyncio.gather(*[_safe_quote(s) for s in NIFTY50])
    quotes  = [r for r in results if r and r.get("day_change_pct") is not None]
    quotes.sort(key=lambda x: x.get("day_change_pct", 0), reverse=True)

    gainers = [{"symbol": q["symbol"], "name": q["company_name"], "price": q["price"], "change_pct": q["day_change_pct"]} for q in quotes[:5]]
    losers  = [{"symbol": q["symbol"], "name": q["company_name"], "price": q["price"], "change_pct": q["day_change_pct"]} for q in quotes[-5:][::-1]]

    result = {"gainers": gainers, "losers": losers, "universe": "Nifty 50", "fetched_at": datetime.utcnow().isoformat() + "Z"}
    return _fmp_store("market:movers", result)


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

# ─── SCREENER.IN INTEGRATION ─────────────────────────────────────────────────

SCREENER_HEADERS = {
    **BROWSER_HEADERS,
    "Referer": "https://www.screener.in/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_screener_data(symbol: str, consolidated: bool = True) -> dict:
    """Fetch clean structured financials from Screener.in for a given NSE/BSE symbol."""
    url_type = "consolidated" if consolidated else "standalone"
    url = f"https://www.screener.in/company/{symbol.upper()}/{url_type}/"
    logger.info(f"Screener.in fetch: {url}")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url, headers=SCREENER_HEADERS)
            if r.status_code == 404 and consolidated:
                url = f"https://www.screener.in/company/{symbol.upper()}/"
                r = await c.get(url, headers=SCREENER_HEADERS)
            if r.status_code != 200:
                raise Exception(
                    f"Screener.in returned HTTP {r.status_code} for '{symbol}'. "
                    f"Verify the symbol is a valid NSE ticker (e.g. RELIANCE, TCS, HDFCBANK)."
                )
            html = r.text
    except Exception as e:
        raise Exception(f"Could not reach Screener.in: {e}")

    result = {
        "symbol": symbol.upper(), "url": url, "consolidated": consolidated,
        "company_name": "", "ratios": {},
        "quarterly_results": [], "annual_results": [], "balance_sheet": [],
        "raw_text": "",
    }

    # Company name — try multiple selectors
    for pat in [r'<h1[^>]*class="[^"]*company-name[^"]*"[^>]*>(.*?)</h1>',
                r'<h1[^>]*>(.*?)</h1>',
                r'<title>([^<|]+)']:
        m = re.search(pat, html, re.S)
        if m:
            name = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if name and len(name) > 2:
                result["company_name"] = name
                break

    # Key ratios — multiple patterns per ratio for robustness
    ratio_defs = [
        ("market_cap",     [r'Market Cap\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("pe_ratio",       [r'Stock P/E\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("book_value",     [r'Book Value\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("dividend_yield", [r'Dividend Yield\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("roce",           [r'\bROCE\b\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("roe",            [r'\bROE\b\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("face_value",     [r'Face Value\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
        ("eps",            [r'EPS\s*(?:\([^)]+\))?\s*</span>[^<]*<span[^>]*>\s*([\d,\.]+)']),
    ]
    for key, patterns in ratio_defs:
        for pat in patterns:
            m = re.search(pat, html, re.S)
            if m:
                val = re.sub(r'<[^>]+>', '', m.group(1)).strip().replace(",", "")
                if val and val != "0":
                    result["ratios"][key] = val
                    break

    # Parse financial table sections
    # Use a robust extractor that handles nested tags by finding the section start
    # and scanning forward to the matching </section> — non-greedy regex fails on large pages
    for section_id, target in [("quarters", "quarterly_results"),
                                ("profit-loss", "annual_results"),
                                ("balance-sheet", "balance_sheet")]:
        section_html = _extract_section(html, section_id)
        if section_html:
            result[target] = _parse_screener_table(section_html)
            logger.info(f"Screener section '{section_id}': {len(result[target])} rows parsed")
        else:
            logger.warning(f"Screener section '{section_id}' not found in HTML")

    if not result["quarterly_results"] and not result["annual_results"]:
        raise Exception(
            f"No financial data found for '{symbol}' on Screener.in. "
            f"Check the symbol spelling (use NSE ticker, e.g. RELIANCE not Reliance Industries)."
        )

    result["raw_text"] = _screener_to_text(result)
    logger.info(
        f"Screener.in {symbol}: qtr={len(result['quarterly_results'])}, "
        f"annual={len(result['annual_results'])}, ratios={list(result['ratios'].keys())}"
    )
    return result


def _extract_section(html: str, section_id: str) -> str:
    """
    Robustly extract a <section id="..."> block from HTML.
    Handles nested tags by counting open/close section tags rather than
    using non-greedy regex (which stops at the first </section> found).
    """
    # Find the opening tag
    import re as _re
    pattern = f'<section[^>]*\\bid="{_re.escape(section_id)}"[^>]*>'
    m = _re.search(pattern, html, _re.S)
    if not m:
        return ""
    start = m.end()
    depth = 1
    pos = start
    while pos < len(html) and depth > 0:
        next_open  = html.find("<section", pos)
        next_close = html.find("</section>", pos)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 8
        else:
            depth -= 1
            if depth == 0:
                return html[start:next_close]
            pos = next_close + 10
    return html[start:pos]


def _parse_screener_table(html_section: str) -> list:
    """
    Parse a Screener.in HTML table into [{label, values, headers}] list.
    Screener uses <th> for header rows and <td> for data rows.
    Header row has empty first cell followed by period labels (Mar 2025, TTM, etc).
    """
    rows = []
    headers = []

    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html_section, re.S):
        # Detect if this is a header row (contains <th> tags)
        has_th = bool(re.search(r'<th[\s>]', tr, re.S))
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)

        def clean(c):
            # Strip HTML tags, decode nbsp, normalise whitespace
            c = re.sub(r'<[^>]+>', '', c)
            c = c.replace('\xa0', ' ').replace('&nbsp;', ' ').replace('\n', ' ')
            return re.sub(r'\s+', ' ', c).strip()

        cells = [clean(c) for c in cells]
        if not cells or not any(c for c in cells):
            continue

        first = cells[0].lower().strip()

        # Header row detection:
        # 1. Row uses <th> tags, OR
        # 2. First cell empty and rest look like period labels, OR
        # 3. First cell is a period label itself (Mar 2025, Dec 2022, TTM...)
        is_period = bool(re.match(
            r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|20\d\d|ttm|fy\d|yr)',
            first
        ))
        is_header = has_th or not first or is_period

        if is_header:
            # Only update headers if this row has actual period content
            period_cells = [c for c in cells[1:] if c]
            if period_cells or not first:
                headers = list(cells)
            continue

        # Data row: must have a label and at least one numeric value
        if cells[0] and any(v for v in cells[1:] if v):
            rows.append({"label": cells[0], "values": cells[1:], "headers": list(headers)})

    return rows


def _screener_to_text(data: dict) -> str:
    """
    Convert Screener.in data to clean text optimised for AI analysis.
    Explicitly pins the latest quarter and YoY comparison values so the AI
    doesn't have to guess which column to use from a 13-column table.
    """
    import re as _re

    def _pin_quarterly(rows: list) -> tuple:
        """
        Extract pinned values for the latest quarter and the same quarter last year.
        Screener quarterly table: columns are quarters in chronological order, LAST column = most recent.
        Returns (latest_period, yoy_period, pinned_lines).
        """
        if not rows:
            return "", "", []
        hdrs = rows[0].get("headers", [])
        # headers[0] is empty label cell, so actual period headers start at index 1
        # but values list starts at index 0 (no label cell in values)
        # So values[0] = hdrs[1], values[-1] = hdrs[-1] = most recent quarter
        if len(hdrs) < 2:
            return "", "", []

        period_hdrs = hdrs[1:]  # strip empty label cell → list of period strings
        latest_idx  = len(period_hdrs) - 1   # rightmost = most recent
        # Find same-quarter prior year: same month name, ~4 quarters back
        latest_label = period_hdrs[latest_idx].lower()
        month_m = _re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', latest_label)
        cur_month = month_m.group(1) if month_m else ""
        yoy_idx = None
        if cur_month:
            for i in range(latest_idx - 3, max(latest_idx - 6, -1), -1):
                if i >= 0 and cur_month in period_hdrs[i].lower():
                    yoy_idx = i
                    break
        if yoy_idx is None and latest_idx >= 4:
            yoy_idx = latest_idx - 4

        latest_period = period_hdrs[latest_idx] if latest_idx < len(period_hdrs) else "Latest Quarter"
        yoy_period    = period_hdrs[yoy_idx] if yoy_idx is not None else "Prior Year Same Quarter"

        pinned = []
        pinned.append(f"  LATEST QUARTER: {latest_period}")
        pinned.append(f"  YoY COMPARISON: {yoy_period}")
        pinned.append("")
        for row in rows:
            vals = row["values"]
            cur_val = vals[latest_idx] if latest_idx < len(vals) else ""
            yoy_val = vals[yoy_idx] if yoy_idx is not None and yoy_idx < len(vals) else ""
            if cur_val and cur_val not in ("-", ""):
                line = f"  {row['label']}: {cur_val}"
                if yoy_val and yoy_val not in ("-", ""):
                    line += f"  [YoY same qtr: {yoy_val}]"
                pinned.append(line)
        return latest_period, yoy_period, pinned

    def _pin_annual(rows: list) -> tuple:
        """
        Extract pinned values for the latest 2 full years.
        Screener annual table: columns in chronological order, LAST = most recent full year.
        Returns (latest_yr, prior_yr, pinned_lines).
        """
        if not rows:
            return "", "", []
        hdrs = rows[0].get("headers", [])
        period_hdrs = hdrs[1:] if hdrs else []
        # Skip TTM column (last) if present — use last full year
        if period_hdrs and "ttm" in period_hdrs[-1].lower():
            period_hdrs = period_hdrs[:-1]
            # adjust values index accordingly
            latest_idx = len(period_hdrs) - 1
            ttm_present = True
        else:
            latest_idx = len(period_hdrs) - 1
            ttm_present = False
        prior_idx = latest_idx - 1 if latest_idx >= 1 else None

        latest_yr = period_hdrs[latest_idx] if latest_idx < len(period_hdrs) else "Latest Year"
        prior_yr  = period_hdrs[prior_idx]  if prior_idx is not None and prior_idx < len(period_hdrs) else "Prior Year"

        # values list doesn't include TTM column if we stripped it — but actually
        # values come from the raw HTML so TTM IS in values[-1] if present
        # We need to use correct index into the values list (which includes TTM)
        hdrs_full = rows[0].get("headers", [])[1:]  # full header list including TTM
        lat_idx_full  = len(hdrs_full) - 1 if not ttm_present else len(hdrs_full) - 2
        pri_idx_full  = lat_idx_full - 1 if lat_idx_full >= 1 else None

        pinned = []
        pinned.append(f"  LATEST FULL YEAR: {latest_yr}")
        pinned.append(f"  PRIOR YEAR: {prior_yr}")
        pinned.append("")
        for row in rows:
            vals = row["values"]
            cur_val = vals[lat_idx_full] if lat_idx_full < len(vals) else ""
            pri_val = vals[pri_idx_full] if pri_idx_full is not None and pri_idx_full < len(vals) else ""
            if cur_val and cur_val not in ("-", ""):
                line = f"  {row['label']}: {cur_val}"
                if pri_val and pri_val not in ("-", ""):
                    line += f"  [Prior year: {pri_val}]"
                pinned.append(line)
        return latest_yr, prior_yr, pinned

    L = []
    L.append(f"COMPANY: {data['company_name']}")
    L.append(f"SYMBOL: {data['symbol']}")
    L.append(f"SOURCE: Screener.in {'Consolidated' if data['consolidated'] else 'Standalone'} — {data['url']}")
    L.append("CURRENCY: INR Crores unless stated otherwise")
    L.append("")

    if data["ratios"]:
        L.append("=== LIVE KEY RATIOS (current market data from Screener.in) ===")
        ratio_labels = {
            "market_cap": "Market Cap (Cr)", "pe_ratio": "Stock P/E",
            "book_value": "Book Value per share (₹)", "dividend_yield": "Dividend Yield (%)",
            "roce": "ROCE (%)", "roe": "ROE (%)", "face_value": "Face Value (₹)", "eps": "EPS TTM (₹)"
        }
        for k, v in data["ratios"].items():
            L.append(f"  {ratio_labels.get(k, k)}: {v}")
        L.append("")

    # ── PINNED QUARTERLY SECTION ──────────────────────────────────────────────
    if data["quarterly_results"]:
        latest_qtr, yoy_qtr, pinned_qtr = _pin_quarterly(data["quarterly_results"])
        L.append(f"╔══════════════════════════════════════════════════╗")
        L.append(f"║  LATEST QUARTERLY RESULTS — {latest_qtr:<20} ║")
        L.append(f"╚══════════════════════════════════════════════════╝")
        L.append(f"  [Current Quarter: {latest_qtr}  |  YoY Comparison: {yoy_qtr}]")
        L.append(f"  [AI INSTRUCTION: Use '{latest_qtr}' values as CURRENT QUARTER metrics]")
        L.append(f"  [AI INSTRUCTION: Use '{yoy_qtr}' values for Year-on-Year growth calculation]")
        L.append("")
        L.extend(pinned_qtr)
        L.append("")

        # Also include full quarterly table for trend analysis
        L.append("--- FULL QUARTERLY TREND (for multi-quarter context) ---")
        hdrs = data["quarterly_results"][0].get("headers", [])
        if hdrs:
            L.append("  " + " | ".join(hdrs))
        for row in data["quarterly_results"]:
            L.append(f"  {row['label']}: {' | '.join(row['values'])}")
        L.append("")

    # ── PINNED ANNUAL SECTION ─────────────────────────────────────────────────
    if data["annual_results"]:
        latest_yr, prior_yr, pinned_ann = _pin_annual(data["annual_results"])
        L.append(f"╔══════════════════════════════════════════════════╗")
        L.append(f"║  LATEST ANNUAL RESULTS — {latest_yr:<24} ║")
        L.append(f"╚══════════════════════════════════════════════════╝")
        L.append(f"  [Latest Full Year: {latest_yr}  |  Prior Year: {prior_yr}]")
        L.append(f"  [AI INSTRUCTION: For cash flow — find 'Cash from Operations', 'Cash from Investing',")
        L.append(f"   'Cash from Financing', 'Capex' rows. Compute OCF/PAT ratio for earnings quality.]")
        L.append("")
        L.extend(pinned_ann)
        L.append("")

        # Full annual table for trend analysis
        L.append("--- FULL ANNUAL TREND (for multi-year context) ---")
        hdrs = data["annual_results"][0].get("headers", [])
        if hdrs:
            L.append("  " + " | ".join(hdrs))
        for row in data["annual_results"]:
            L.append(f"  {row['label']}: {' | '.join(row['values'])}")
        L.append("")

    if data["balance_sheet"]:
        L.append("=== BALANCE SHEET (INR Cr) ===")
        hdrs = data["balance_sheet"][0].get("headers", [])
        if hdrs:
            L.append("  Years: " + " | ".join(hdrs))
        for row in data["balance_sheet"]:
            L.append(f"  {row['label']}: {' | '.join(row['values'])}")
        L.append("")

    L.append("=== ANALYSIS INSTRUCTIONS ===")
    L.append("1. QUARTERLY ANALYSIS: Use the pinned LATEST QUARTERLY RESULTS block above.")
    L.append("   Report: Revenue, Operating Profit, OPM%, Net Profit, EPS for latest quarter vs YoY.")
    L.append("2. ANNUAL ANALYSIS: Use the pinned LATEST ANNUAL RESULTS block above.")
    L.append("   Report: Full year revenue, PAT, margins, cash flow quality (OCF/PAT ratio).")
    L.append("3. The analysis must cover BOTH latest quarter AND latest full year — not just one.")
    L.append("4. LIVE RATIOS: Use ROE, ROCE, P/E from the live ratios block — these are current values.")
    L.append("5. CASH FLOW: Annual data has cash flow rows. Find them and compute FCF = OCF - Capex.")
    L.append("6. SPECIFICITY: Every sentence needs actual numbers. No vague statements.")

    return "\n".join(L)


class ScreenerAnalyzeRequest(BaseModel):
    symbol: str
    consolidated: bool = True


@app.post("/api/analyze-from-screener")
async def analyze_from_screener(req: ScreenerAnalyzeRequest, user=Depends(get_optional_user)):
    """
    Fetch live data from Screener.in and run full AI analysis.
    More reliable than PDF: no font-encoding issues, always latest annual data with cash flows.
    """
    analysis_id = str(uuid.uuid4())
    user_id = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"

    await analyses_col.insert_one({
        "analysis_id": analysis_id, "user_id": user_id, "is_guest": user is None,
        "filename": f"{req.symbol.upper()}_screener",
        "source": "screener", "status": "processing",
        "created_at": datetime.utcnow().isoformat(), "result": None,
    })

    try:
        logger.info(f"Screener analysis: {req.symbol} (consolidated={req.consolidated})")
        data = await fetch_screener_data(req.symbol, req.consolidated)

        if not data["raw_text"] or len(data["raw_text"].strip()) < 200:
            raise Exception(
                f"Screener.in returned insufficient data for '{req.symbol}'. "
                f"Try the exact NSE ticker symbol."
            )

        result = await run_analysis(data["raw_text"])

        meta = {
            "company_name": data["company_name"],
            "url": data["url"],
            "ratios": data["ratios"],
        }
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "completed", "result": result, "screener_meta": meta}},
        )
        logger.info(f"Screener complete: {req.symbol} → {analysis_id}")
        return {
            "analysis_id": analysis_id, "status": "completed",
            "result": result, "screener_meta": meta
        }

    except Exception as e:
        msg = str(e)
        logger.error(f"Screener failed {analysis_id} ({req.symbol}): {msg}")
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "failed", "message": msg}},
        )
        return {"analysis_id": analysis_id, "status": "failed", "message": msg}


@app.get("/api/screener/{symbol}")
async def get_screener_preview(symbol: str, consolidated: bool = True):
    """Return raw Screener.in data for a symbol (no AI analysis — useful for debugging)."""
    try:
        data = await fetch_screener_data(symbol, consolidated)
        data.pop("raw_text", None)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
            raise Exception(f"Could not fetch PDF — HTTP {r.status_code}.")
        if "html" in r.headers.get("content-type", "").lower():
            raise Exception("Server returned HTML instead of PDF. Filing link may have expired.")
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(executor, extract_pdf_text, r.content)
        result = await run_analysis(text)
        await analyses_col.update_one({"analysis_id": analysis_id}, {"$set": {"status": "completed", "result": result}})
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
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post("https://api.html2pdf.app/v1/generate",
                    json={"html": html_content, "apiKey": HTML2PDF_KEY, "zoom": 1, "landscape": False,
                          "marginTop": 10, "marginBottom": 10, "marginLeft": 10, "marginRight": 10},
                    headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                return Response(content=r.content, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=FinSight_Analysis.pdf"})
            last_error = f"html2pdf.app {r.status_code}: {r.text[:200]}"
        except httpx.TimeoutException:
            last_error = f"Attempt {attempt} timed out"
        except Exception as e:
            last_error = str(e)
        if attempt < 3: await asyncio.sleep(3)
    raise HTTPException(504, f"PDF generation failed after 3 attempts. {last_error}")


@app.post("/api/debug/extract")
async def debug_extract(file: UploadFile = File(...)):
    """Debug endpoint: returns raw pypdf text + extraction results for a PDF."""
    raw = await file.read()
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages_text = {}
        for i, page in enumerate(reader.pages[:20]):
            t = page.extract_text() or ""
            if t.strip():
                pages_text[f"page_{i+1}"] = t[:3000]

        page_indices = _select_financial_pages(raw)
        extracted = _extract_deterministic(raw, page_indices)

        return {
            "page_count": len(reader.pages),
            "selected_pages": [p+1 for p in page_indices],
            "raw_text_per_page": pages_text,
            "extraction_result": {
                "company_name": extracted["company_name"],
                "period": extracted["period"],
                "filing_type": extracted["filing_type"],
                "pl_keys_found": list(extracted["pl"].keys()),
                "ratio_keys_found": list(extracted["ratios"].keys()),
                "segment_keys_found": list(extracted["segments"].keys()),
                "pl_details": extracted["pl"],
                "ratio_details": extracted["ratios"],
                "extraction_log": extracted["extraction_log"],
            }
        }
    except Exception as e:
        return {"error": str(e)}
