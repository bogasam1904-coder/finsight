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
app = FastAPI(title="FinSight API v13")

# ─── CORS ────────────────────────────────────────────────────────────────────
# Explicit CORSMiddleware (belt) + custom middleware (suspenders)
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
                if r.status_code != 200:
                    logger.warning(f"BSE API {cat} returned {r.status_code} for {bse_code}")
                    continue
                items = r.json().get("Table", [])
                logger.info(f"BSE {cat}: {len(items)} items for {bse_code}")

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


# ─── PDF EXTRACTION ──────────────────────────────────────────────────────────

def extract_tables_from_pdf(raw_bytes: bytes):
    """
    Extract structured tables using pdfplumber.
    Returns list of tables with rows preserved.
    """
    tables = []
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                extracted = page.extract_tables()
                for table in extracted:
                    clean_table = []
                    for row in table:
                        cleaned = [str(cell).strip() if cell else "" for cell in row]
                        if any(cleaned):
                            clean_table.append(cleaned)
                    if clean_table:
                        tables.append({"page": page_num + 1, "rows": clean_table})
        logger.info(f"Extracted {len(tables)} tables")
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")
    return tables


def parse_financial_metrics(tables):
    """
    Extract key financial metrics from tables.
    """
    metrics = defaultdict(str)
    keywords = {
        "revenue": ["revenue", "total income", "income from operations", "net sales", "revenue from operations"],
        "revenue_previous": ["previous revenue", "prior year revenue"],
        "gross_profit": ["gross profit", "gross income"],
        "ebitda": ["ebitda", "operating profit before depreciation"],
        "ebit": ["ebit", "operating profit"],
        "net_profit": ["net profit", "profit after tax", "pat", "profit for the period"],
        "pbt": ["profit before tax", "pbt"],
        "other_income": ["other income"],
        "finance_cost": ["finance cost", "interest expense", "finance charges"],
        "depreciation": ["depreciation", "amortisation", "amortization", "d&a"],
        "tax_expense": ["tax expense", "income tax", "provision for tax"],
        "eps_basic": ["basic eps", "basic earnings per share"],
        "eps_diluted": ["diluted eps", "diluted earnings per share", "earnings per share", "eps"],
        "total_assets": ["total assets"],
        "current_assets": ["current assets", "total current assets"],
        "non_current_assets": ["non-current assets", "non current assets", "fixed assets"],
        "cash_equivalents": ["cash and cash equivalents", "cash & cash equivalents", "cash and bank"],
        "inventory": ["inventories", "inventory", "stock in trade"],
        "accounts_receivable": ["trade receivables", "accounts receivable", "debtors"],
        "total_liabilities": ["total liabilities"],
        "current_liabilities": ["current liabilities", "total current liabilities"],
        "non_current_liabilities": ["non-current liabilities", "non current liabilities"],
        "borrowings": ["borrowings", "total debt", "loans", "long-term borrowings", "short-term borrowings"],
        "total_equity": ["total equity", "shareholders equity", "net worth", "stockholders equity"],
        "reserves_surplus": ["reserves and surplus", "reserves & surplus"],
        "share_capital": ["share capital", "equity capital"],
        "operating_cash_flow": ["cash flow from operating", "net cash from operations", "operating cash flow", "ocf"],
        "investing_cash_flow": ["cash flow from investing", "investing activities"],
        "financing_cash_flow": ["cash flow from financing", "financing activities"],
        "free_cash_flow": ["free cash flow", "fcf"],
        "capex": ["capital expenditure", "capex", "purchase of fixed assets", "additions to property"],
        "current_ratio": ["current ratio"],
        "quick_ratio": ["quick ratio", "acid test ratio", "acid-test ratio"],
        "debt_equity_ratio": ["debt to equity", "debt/equity", "d/e ratio"],
        "debt_ebitda_ratio": ["debt/ebitda", "debt to ebitda"],
        "interest_coverage": ["interest coverage", "interest cover", "ebit/interest"],
        "inventory_turnover": ["inventory turnover", "stock turnover"],
        "asset_turnover": ["asset turnover", "total asset turnover"],
        "roe": ["return on equity", "roe"],
        "roa": ["return on assets", "roa"],
        "roic": ["return on invested capital", "roic", "return on capital employed", "roce"],
        "gross_margin": ["gross margin", "gross profit margin"],
        "ebitda_margin": ["ebitda margin"],
        "net_margin": ["net profit margin", "net margin", "pat margin"],
        "dividend_yield": ["dividend yield"],
        "book_value": ["book value per share", "bvps", "net asset value per share"],
        "price_earnings": ["price to earnings", "p/e ratio", "pe ratio"],
    }

    for table in tables:
        for row in table["rows"]:
            row_text = " ".join(row).lower()
            for metric, keys in keywords.items():
                if metrics.get(metric):
                    continue
                if any(k in row_text for k in keys):
                    numbers = re.findall(r'-?\d[\d,\.]*', row_text)
                    if numbers:
                        metrics[metric] = numbers[0]

    logger.info(f"Extracted metrics: {dict(metrics)}")
    return dict(metrics)


def compute_financial_ratios(metrics: dict) -> dict:
    """
    Compute derived financial ratios from raw extracted metrics.
    """
    def _to_float(val: str) -> Optional[float]:
        if not val:
            return None
        try:
            return float(str(val).replace(",", "").replace("%", "").strip())
        except (ValueError, TypeError):
            return None

    def _pct(num, denom) -> Optional[str]:
        n, d = _to_float(num), _to_float(denom)
        if n is not None and d and d != 0:
            return f"{round((n / d) * 100, 2)}%"
        return None

    def _ratio(num, denom, decimals=2) -> Optional[str]:
        n, d = _to_float(num), _to_float(denom)
        if n is not None and d and d != 0:
            return str(round(n / d, decimals))
        return None

    ratios: dict = {}

    rev      = metrics.get("revenue")
    pat      = metrics.get("net_profit")
    ebitda   = metrics.get("ebitda")
    ebit     = metrics.get("ebit")
    gross    = metrics.get("gross_profit")
    debt     = metrics.get("borrowings")
    equity   = metrics.get("total_equity")
    curr_a   = metrics.get("current_assets")
    curr_l   = metrics.get("current_liabilities")
    cash     = metrics.get("cash_equivalents")
    inv      = metrics.get("inventory")
    assets   = metrics.get("total_assets")
    ocf      = metrics.get("operating_cash_flow")
    fin_cost = metrics.get("finance_cost")
    rev_prev = metrics.get("revenue_previous")

    r = _pct(gross, rev)
    if r: ratios["gross_margin_pct"] = r
    r = _pct(ebitda, rev)
    if r: ratios["ebitda_margin_pct"] = r
    r = _pct(ebit, rev)
    if r: ratios["ebit_margin_pct"] = r
    r = _pct(pat, rev)
    if r: ratios["net_profit_margin_pct"] = r
    r = _pct(pat, equity)
    if r: ratios["return_on_equity_pct"] = r
    r = _pct(pat, assets)
    if r: ratios["return_on_assets_pct"] = r
    r = _ratio(debt, equity)
    if r: ratios["debt_to_equity"] = r
    r = _ratio(debt, ebitda)
    if r: ratios["debt_to_ebitda"] = r
    r = _ratio(ebit or ebitda, fin_cost)
    if r: ratios["interest_coverage_ratio"] = r
    r = _ratio(curr_a, curr_l)
    if r: ratios["current_ratio"] = r

    ca_f  = _to_float(curr_a)
    inv_f = _to_float(inv) or 0.0
    cl_f  = _to_float(curr_l)
    if ca_f is not None and cl_f and cl_f != 0:
        ratios["quick_ratio"] = str(round((ca_f - inv_f) / cl_f, 2))

    r = _ratio(cash, curr_l)
    if r: ratios["cash_ratio"] = r
    r = _ratio(rev, assets)
    if r: ratios["asset_turnover"] = r
    r = _ratio(rev, inv)
    if r: ratios["inventory_turnover"] = r
    r = _ratio(ocf, curr_l)
    if r: ratios["ocf_to_current_liabilities"] = r

    if rev and rev_prev:
        rev_f  = _to_float(rev)
        prev_f = _to_float(rev_prev)
        if rev_f is not None and prev_f and prev_f != 0:
            growth = ((rev_f - prev_f) / abs(prev_f)) * 100
            ratios["revenue_growth_yoy_pct"] = f"{round(growth, 2)}%"

    logger.info(f"Computed ratios: {ratios}")
    return ratios


def _extract_with_pdfplumber(raw_bytes: bytes, page_indices: list) -> str:
    """
    Use pdfplumber for superior table extraction.
    """
    try:
        import pdfplumber
        result = ""
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for i in page_indices:
                if i >= len(pdf.pages):
                    continue
                page = pdf.pages[i]
                page_text = ""
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        cleaned = [str(cell).strip() if cell else "" for cell in row]
                        if any(cleaned):
                            page_text += " | ".join(cleaned) + "\n"
                raw_text = page.extract_text() or ""
                if raw_text.strip():
                    page_text += raw_text
                if page_text.strip():
                    result += f"\n--- PAGE {i+1} ---\n{page_text}\n"
        logger.info(f"pdfplumber extracted {len(result):,} chars")
        return result
    except ImportError:
        logger.warning("pdfplumber not available, falling back to pypdf")
        return ""
    except Exception as e:
        logger.warning(f"pdfplumber failed: {e}, falling back to pypdf")
        return ""


def _select_financial_pages(raw_bytes: bytes) -> list:
    """
    Score every page by financial keyword density.
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
        "revenue from operations", "other income", "tax expense",
        "depreciation", "amortisation", "reserves and surplus",
    ]

    core_pages = set(range(min(5, total)))
    for i, page in enumerate(reader.pages):
        t = (page.extract_text() or "").lower()
        score = sum(1 for kw in KEYWORDS if kw in t)
        if score >= 2:
            core_pages.add(i)

    logger.info(f"PDF: {total} pages total, {len(core_pages)} financial pages selected: {sorted(core_pages)}")
    return sorted(core_pages)


def extract_financial_snippet(raw_bytes: bytes, max_chars: int = 60000) -> str:
    """
    Full extraction pipeline with pdfplumber primary, pypdf fallback.
    """
    page_indices = _select_financial_pages(raw_bytes)
    result = _extract_with_pdfplumber(raw_bytes, page_indices)

    if not result.strip():
        logger.info("Falling back to pypdf extraction")
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        result = ""
        for i in page_indices:
            pt = reader.pages[i].extract_text() or ""
            if pt.strip():
                result += f"\n--- PAGE {i+1} ---\n{pt}\n"
        logger.info(f"pypdf extracted {len(result):,} chars")

    doc_type_hint = ""
    lower_result = result.lower()
    is_partial = (
        "newspaper" in lower_result or
        "business standard" in lower_result or
        "extract of" in lower_result or
        "advertisement" in lower_result or
        len(result) < 3000
    )
    if is_partial:
        doc_type_hint = (
            "\n\n[SYSTEM NOTE: This appears to be a NEWSPAPER EXTRACT or PARTIAL FILING. "
            "It likely contains only: Revenue, PBT, PAT, EPS, and Equity Capital. "
            "DO NOT fabricate Balance Sheet items (Debt, Current Ratio, Cash, OCF) "
            "that are not present. Mark them as 'Not available in this filing extract'. "
            "Use only numbers explicitly present in the document.]\n"
        )
        logger.warning("Partial/newspaper extract detected — hallucination guard injected")

    final = (doc_type_hint + result)[:max_chars]
    logger.info(f"Final snippet: {len(final):,} chars (partial={is_partial})")
    return final


def extract_pdf_text(raw_bytes: bytes) -> str:
    """
    Entry point for PDF processing.
    """
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

        logger.info(f"PDF validated: {num_pages} pages, extracting financial sections...")
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

def split_into_chunks(text, size=12000, overlap=1200):
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + size]
        chunks.append(chunk)
        start += size - overlap
    logger.info(f"Split document into {len(chunks)} chunks of ~{size} chars")
    return chunks

def build_prompt(text: str, max_doc_chars: int = 44000) -> str:
    snippet = text[:max_doc_chars]
    logger.info(f"build_prompt: {len(snippet):,} chars (from {len(text):,} total)")
    return f"""Analyze the provided financial document and return ONLY one valid JSON object. Do not include markdown, explanations, code fences, or additional commentary. The response must strictly conform to the JSON schema provided below.

ANALYTICAL OBJECTIVE
Produce an institutional-grade equity research assessment suitable for professional investors. The analysis must interpret financial performance, identify hidden signals, and explain what the data implies for capital allocation decisions. The final output should resemble analysis prepared by a senior equity research analyst at a global investment bank.

CORE PRINCIPLES
Interpret numbers rather than merely restating them. Always explain what the data implies about the company's underlying business performance.
Contextualize metrics within the company's business model and industry structure.
Identify non-obvious signals such as margin trends, working capital shifts, leverage changes, or capital allocation patterns.
Avoid vague language. Use precise statements supported by extracted numbers.
Assume the analysis will inform real investment decisions and maintain analytical rigor.
Highlight risks even when performance appears strong to maintain intellectual honesty.

DATA EXTRACTION PROTOCOL
Before performing analysis, scan the entire document for financial data.
Search the entire document for each metric. Only state "Not reported" when the metric cannot be derived from any section.

Recognize alternate metric names:
Total Assets may appear as Assets or Balance Sheet Total.
Total Debt may appear as Borrowings, Loans, or Debt Securities.
Operating Cash Flow may appear as Net Cash from Operating Activities.
Interest Coverage may need to be calculated using EBIT divided by Finance Costs.
Free Cash Flow equals Operating Cash Flow minus Capex.

Sector-specific adjustments:
For NBFC or financial institutions, Total Debt equals Debt Securities plus Borrowings plus Subordinated Liabilities.
For defense or PSU companies, carefully examine order book disclosures, government contracts, and advances from customers because these determine revenue visibility.

DERIVED METRICS
Calculate ratios whenever raw inputs are available.
ROE = Net Profit divided by Total Equity
ROA = Net Profit divided by Total Assets
Debt to Equity = Total Debt divided by Total Equity
Interest Coverage = EBIT divided by Finance Costs
Current Ratio = Current Assets divided by Current Liabilities
Free Cash Flow = Operating Cash Flow minus Capex
Do not leave ratios blank if they can be calculated.

SCORING FRAMEWORK

Profitability (0-20):
Strong (score 20): ROE >20% AND Net Margin >15%
Average (score 12): ROE 12-20% OR Net Margin 8-15%
Weak (score 5): ROE <12% OR Net Margin <8%

Growth (0-15):
Strong (score 15): Revenue growth >20% AND Profit growth >25%
Average (score 9): Revenue growth 10-20% AND Profit growth 10-25%
Weak (score 4): Revenue growth <10% OR Profit growth <10%

Balance Sheet (0-15):
Strong (score 15): Debt-to-Equity <0.5
Average (score 9): Debt-to-Equity 0.5-1.5
Weak (score 3): Debt-to-Equity >1.5

Liquidity (0-10):
Strong (score 10): Current Ratio >1.5
Average (score 6): Current Ratio 1.0-1.5
Weak (score 2): Current Ratio <1.0

Cash Flow (0-15):
Strong (score 15): Operating cash flow exceeds net profit
Average (score 9): Operating cash flow approximately equal to net profit
Weak (score 3): Operating cash flow materially below net profit

Governance & Risk (0-15):
Strong (score 15): Clean audit opinion, strong ratings, minimal promoter pledging
Average (score 9): Minor governance concerns
Weak (score 3): Auditor qualifications or major governance risks

Industry Position (0-10):
Strong (score 10): Market leadership and durable competitive advantages
Average (score 6): Comparable to peers
Weak (score 2): Lagging peers or losing competitive position

Health Label thresholds: score >=80 = Excellent | 60-79 = Good | 40-59 = Fair | 20-39 = Poor | 0-19 = Critical
investment_label options: Strong Buy / Buy / Hold / Reduce / Avoid

ANALYTICAL EXPECTATIONS
The analysis must clearly evaluate profitability quality, growth durability, capital allocation efficiency, cash flow integrity, balance sheet resilience, and competitive positioning.

RISK IDENTIFICATION
Explicitly surface hidden risks such as working capital stress, margin compression, revenue concentration, government dependency, order book volatility, customer concentration, accounting anomalies, or excessive capex intensity. Each risk must include explanation, investor relevance, and a measurable trigger to monitor.

INVESTOR-ORIENTED OUTPUT
Address both long-term investors and short-term traders.
Long-term analysis should evaluate moat durability, compounding potential, and permanent capital loss risk.
Short-term analysis should focus on catalysts, triggers for the next earnings cycle, and operational momentum indicators.

ANALYTICAL STYLE
Write in the tone of professional sell-side equity research: concise, analytical, and evidence-based. Avoid boilerplate commentary or generic financial explanations.

Return ONLY this exact JSON object with every field populated. Use specific numbers in every commentary field:

{{
  "company_name": "Full legal name from document",
  "statement_type": "Annual Report / Half-Year Results / Quarterly Results",
  "period": "Reporting period e.g. Q3FY26 / FY2024-25",
  "currency": "INR Lakhs / INR Crores / USD Millions",
  "health_score": 0,
  "health_label": "Excellent / Good / Fair / Poor / Critical",

  "health_score_breakdown": {{
    "total": 0,
    "components": [
      {{"category": "Profitability", "weight": 20, "score": 0, "max": 20, "rating": "Strong / Average / Weak", "reasoning": "Explain ROE, margins, and profitability trend with specific numbers."}},
      {{"category": "Growth",        "weight": 15, "score": 0, "max": 15, "rating": "Strong / Average / Weak", "reasoning": "Explain revenue and profit growth drivers with specific numbers."}},
      {{"category": "Balance Sheet", "weight": 15, "score": 0, "max": 15, "rating": "Strong / Average / Weak", "reasoning": "Discuss leverage, debt structure, and asset quality with specific numbers."}},
      {{"category": "Liquidity",     "weight": 10, "score": 0, "max": 10, "rating": "Strong / Average / Weak", "reasoning": "Evaluate short-term financial strength with specific numbers."}},
      {{"category": "Cash Flow",     "weight": 15, "score": 0, "max": 15, "rating": "Strong / Average / Weak", "reasoning": "Explain OCF vs PAT relationship and cash generation quality."}},
      {{"category": "Governance & Risk", "weight": 15, "score": 0, "max": 15, "rating": "Strong / Average / Weak", "reasoning": "Evaluate governance, audit opinion, and structural risks."}},
      {{"category": "Industry Position", "weight": 10, "score": 0, "max": 10, "rating": "Strong / Average / Weak", "reasoning": "Compare position versus industry peers."}}
    ]
  }},

  "headline": "One concise memorable sentence summarizing the result",
  "executive_summary": "5-6 sentences explaining the most important story behind the numbers. Every sentence must contain specific numbers.",
  "investment_label": "Strong Buy / Buy / Hold / Reduce / Avoid",
  "investor_verdict": "Direct institutional recommendation with reasoning and specific numbers",
  "for_long_term_investors": "Moat durability, compounding potential, long-term risk with specific numbers",
  "for_short_term_traders": "Near-term catalysts and earnings triggers with specific numbers",
  "bottom_line": "Single memorable sentence capturing the key investment insight",

  "key_metrics": [
    {{"label": "Revenue",             "current": "", "previous": "", "change": "", "trend": "up/down/flat", "signal": "Bullish/Bearish/Neutral", "comment": ""}},
    {{"label": "Net Profit",          "current": "", "previous": "", "change": "", "trend": "up/down/flat", "signal": "Bullish/Bearish/Neutral", "comment": ""}},
    {{"label": "EBITDA Margin",       "current": "", "previous": "", "change": "", "trend": "up/down/flat", "signal": "Bullish/Bearish/Neutral", "comment": ""}},
    {{"label": "ROE",                 "current": "", "previous": "", "change": "", "trend": "up/down/flat", "signal": "Bullish/Bearish/Neutral", "comment": ""}},
    {{"label": "Debt to Equity",      "current": "", "previous": "", "change": "", "trend": "up/down/flat", "signal": "Bullish/Bearish/Neutral", "comment": ""}},
    {{"label": "Operating Cash Flow", "current": "", "previous": "", "change": "", "trend": "up/down/flat", "signal": "Bullish/Bearish/Neutral", "comment": ""}}
  ],

  "cash_flow_deep_dive": {{
    "operating_cf":          "extracted value with unit",
    "investing_cf":          "extracted value with unit",
    "financing_cf":          "extracted value with unit",
    "free_cash_flow":        "calculated: OCF minus Capex with unit",
    "capex":                 "extracted value with unit",
    "cash_conversion_quality": "Strong / Moderate / Weak",
    "ocf_vs_pat_insight":    "Is OCF greater than PAT? What does this say about earnings quality? Use specific numbers."
  }},

  "balance_sheet_deep_dive": {{
    "asset_quality":         "Institutional commentary on fixed vs current asset mix with numbers",
    "debt_profile":          "ST vs LT split, maturity profile, rates if available",
    "working_capital_insight": "Receivables, payables, inventory cycle commentary with days",
    "total_debt":            "extracted value with unit",
    "net_worth":             "extracted value with unit",
    "debt_to_equity":        "calculated ratio",
    "interest_coverage":     "calculated ratio",
    "debt_comfort_level":    "Comfortable / Elevated / Stressed"
  }},

  "growth_quality": {{
    "revenue_growth_context":  "Organic vs inorganic, volume vs price drivers with numbers",
    "profit_growth_context":   "Operating leverage, margin expansion/compression drivers",
    "margin_trend":            "Direction and magnitude of margin changes with basis points",
    "growth_outlook":          "Forward-looking assessment based on order book, guidance, or sector trends",
    "catalysts":               ["List of specific near-term growth catalysts"],
    "headwinds":               ["List of specific risks that could impair growth"]
  }},

  "industry_context": {{
    "sector_tailwinds":       ["List of structural or cyclical tailwinds"],
    "sector_headwinds":       ["List of structural or cyclical headwinds"],
    "competitive_position":   "Market share, pricing power, barriers to entry",
    "peer_benchmarks":        "How key ratios compare to sector averages or named peers",
    "regulatory_environment": "Relevant regulations, government policies, or compliance risks"
  }},

  "red_flags":          ["Each as a specific, evidence-backed concern with numbers"],
  "strengths_and_moats": ["Each as a specific, defensible competitive advantage"],

  "investor_faq": [
    {{"question": "Is this company a good investment right now?", "answer": "Direct answer with numbers and reasoning"}},
    {{"question": "What is the biggest risk to monitor?",         "answer": "Specific risk with measurable trigger"}},
    {{"question": "How sustainable is the current growth rate?",  "answer": "Evidence-based assessment"}}
  ],

  "key_monitorables": ["Specific metric or event to track each quarter with threshold"],

  "profitability": {{
    "analysis":             "2-3 sentence institutional commentary with specific numbers",
    "net_margin_current":   "",
    "ebitda_margin_current":"",
    "roe":                  "",
    "roa":                  ""
  }},

  "liquidity": {{
    "analysis":          "2-3 sentence institutional commentary with specific numbers",
    "current_ratio":     "",
    "quick_ratio":       "",
    "cash_position":     "",
    "operating_cash_flow":"",
    "free_cash_flow":    ""
  }},

  "highlights":    ["Key positive takeaways with specific numbers"],
  "risks":         ["Key risk factors with specific numbers and triggers"],
  "what_to_watch": ["Forward-looking items to monitor next quarter"]
}}

FINAL INSTRUCTIONS:
- Use only numbers extracted from the document. Do not fabricate data.
- Calculate all ratios where inputs are available.
- Ensure scores match the scoring framework exactly.
- Every commentary field must contain specific numbers, not vague statements.
- Return only the JSON object, nothing else.

FINANCIAL DOCUMENT:
{snippet}
"""


def build_lean_prompt(text: str, max_doc_chars: int = 18000) -> str:
    snippet = text[:max_doc_chars]
    logger.info(f"build_lean_prompt: {len(snippet):,} chars (from {len(text):,} total)")
    return f"""Analyze this financial document and return ONLY valid JSON — no markdown, no preamble, no code fences.

You are a senior equity research analyst. Extract all numbers exactly as written. Calculate all derivable ratios. Write institutional-quality commentary with specific numbers in every field.

SCORING (use exact scores):
Profitability(max 20): ROE>20% AND Margin>15%=20 | ROE 12-20% OR Margin 8-15%=12 | else=5
Growth(max 15): Rev>20% AND Profit>25%=15 | Rev 10-20% AND Profit 10-25%=9 | else=4
Balance Sheet(max 15): D/E<0.5=15 | D/E 0.5-1.5=9 | D/E>1.5=3
Liquidity(max 10): CR>1.5=10 | CR 1.0-1.5=6 | CR<1.0=2
Cash Flow(max 15): OCF>PAT=15 | OCF~PAT=9 | OCF<PAT=3
Governance(max 15): Clean audit=15 | Minor issues=9 | Major issues=3
Industry(max 10): Leader=10 | Average=6 | Lagging=2
health_label: >=80=Excellent | 60-79=Good | 40-59=Fair | 20-39=Poor | <20=Critical
investment_label: Strong Buy / Buy / Hold / Reduce / Avoid

Return ONLY this JSON (all fields required, use specific numbers in all commentary):
{{
  "company_name":"","statement_type":"","period":"","currency":"","health_score":0,"health_label":"",
  "health_score_breakdown":{{
    "total":0,
    "components":[
      {{"category":"Profitability","weight":20,"score":0,"max":20,"rating":"","reasoning":""}},
      {{"category":"Growth","weight":15,"score":0,"max":15,"rating":"","reasoning":""}},
      {{"category":"Balance Sheet","weight":15,"score":0,"max":15,"rating":"","reasoning":""}},
      {{"category":"Liquidity","weight":10,"score":0,"max":10,"rating":"","reasoning":""}},
      {{"category":"Cash Flow","weight":15,"score":0,"max":15,"rating":"","reasoning":""}},
      {{"category":"Governance & Risk","weight":15,"score":0,"max":15,"rating":"","reasoning":""}},
      {{"category":"Industry Position","weight":10,"score":0,"max":10,"rating":"","reasoning":""}}
    ]
  }},
  "headline":"","executive_summary":"","investment_label":"","investor_verdict":"",
  "for_long_term_investors":"","for_short_term_traders":"","bottom_line":"",
  "key_metrics":[
    {{"label":"Revenue","current":"","previous":"","change":"","trend":"","signal":"","comment":""}},
    {{"label":"Net Profit","current":"","previous":"","change":"","trend":"","signal":"","comment":""}},
    {{"label":"EBITDA Margin","current":"","previous":"","change":"","trend":"","signal":"","comment":""}},
    {{"label":"ROE","current":"","previous":"","change":"","trend":"","signal":"","comment":""}},
    {{"label":"Debt to Equity","current":"","previous":"","change":"","trend":"","signal":"","comment":""}},
    {{"label":"Operating Cash Flow","current":"","previous":"","change":"","trend":"","signal":"","comment":""}}
  ],
  "cash_flow_deep_dive":{{
    "operating_cf":"","investing_cf":"","financing_cf":"","free_cash_flow":"","capex":"",
    "cash_conversion_quality":"","ocf_vs_pat_insight":""
  }},
  "balance_sheet_deep_dive":{{
    "asset_quality":"","debt_profile":"","working_capital_insight":"",
    "total_debt":"","net_worth":"","debt_to_equity":"","interest_coverage":"","debt_comfort_level":""
  }},
  "growth_quality":{{"revenue_growth_context":"","profit_growth_context":"","margin_trend":"","growth_outlook":"","catalysts":[],"headwinds":[]}},
  "industry_context":{{"sector_tailwinds":[],"sector_headwinds":[],"competitive_position":"","peer_benchmarks":"","regulatory_environment":""}},
  "red_flags":[],"strengths_and_moats":[],
  "investor_faq":[
    {{"question":"Is this company a good investment right now?","answer":""}},
    {{"question":"What is the biggest risk to monitor?","answer":""}},
    {{"question":"How sustainable is the current growth rate?","answer":""}}
  ],
  "key_monitorables":[],
  "profitability":{{"analysis":"","net_margin_current":"","ebitda_margin_current":"","roe":"","roa":""}},
  "liquidity":{{"analysis":"","current_ratio":"","quick_ratio":"","cash_position":"","operating_cash_flow":"","free_cash_flow":""}},
  "highlights":[],"risks":[],"what_to_watch":[]
}}

FINANCIAL DOCUMENT:
{snippet}
"""


def _extract_metrics_from_text(text: str) -> dict:
    """
    Regex-based metric extraction directly from extracted text.
    """
    metrics = defaultdict(str)
    NUM = r'[-]?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?'

    patterns = {
        "revenue":            [r'(?:revenue from operations|net revenue|total revenue|income from operations)[^\n]{0,40}?(' + NUM + r')', r'(?:net sales|sales)[^\n]{0,30}?(' + NUM + r')'],
        "total_income":       [r'total income[^\n]{0,30}?(' + NUM + r')'],
        "gross_profit":       [r'gross profit[^\n]{0,30}?(' + NUM + r')'],
        "ebitda":             [r'ebitda[^\n]{0,30}?(' + NUM + r')', r'operating profit before[^\n]{0,40}?(' + NUM + r')'],
        "ebit":               [r'\bebit\b[^\n]{0,30}?(' + NUM + r')', r'operating profit[^\n]{0,30}?(' + NUM + r')'],
        "finance_cost":       [r'finance costs?[^\n]{0,30}?(' + NUM + r')', r'interest expense[^\n]{0,30}?(' + NUM + r')', r'finance charges[^\n]{0,30}?(' + NUM + r')'],
        "depreciation":       [r'depreciation[^\n]{0,60}?(' + NUM + r')', r'amortis[^\n]{0,40}?(' + NUM + r')'],
        "pbt":                [r'profit before tax[^\n]{0,30}?(' + NUM + r')', r'\bpbt\b[^\n]{0,30}?(' + NUM + r')'],
        "tax_expense":        [r'tax expense[^\n]{0,30}?(' + NUM + r')', r'income tax[^\n]{0,30}?(' + NUM + r')'],
        "net_profit":         [r'profit (?:after tax|for the (?:year|period|quarter))[^\n]{0,30}?(' + NUM + r')', r'(?:^|\s)pat\b[^\n]{0,30}?(' + NUM + r')', r'net profit[^\n]{0,30}?(' + NUM + r')'],
        "eps_basic":          [r'basic (?:eps|earnings per share)[^\n]{0,30}?(' + NUM + r')', r'(?:eps|earnings per share)[^\n\-]{0,20}basic[^\n]{0,20}?(' + NUM + r')'],
        "eps_diluted":        [r'diluted (?:eps|earnings per share)[^\n]{0,30}?(' + NUM + r')'],
        "total_assets":       [r'total assets[^\n]{0,30}?(' + NUM + r')'],
        "current_assets":     [r'total current assets[^\n]{0,30}?(' + NUM + r')', r'current assets[^\n]{0,30}?(' + NUM + r')'],
        "inventories":        [r'inventor(?:y|ies)[^\n]{0,30}?(' + NUM + r')'],
        "trade_receivables":  [r'trade receivables[^\n]{0,30}?(' + NUM + r')', r'accounts receivable[^\n]{0,30}?(' + NUM + r')'],
        "cash_equivalents":   [r'cash and (?:cash )?equivalents[^\n]{0,30}?(' + NUM + r')', r'cash & (?:cash )?equivalents[^\n]{0,30}?(' + NUM + r')'],
        "total_equity":       [r'total equity[^\n]{0,30}?(' + NUM + r')', r'(?:shareholders|stockholders)[\'s]* equity[^\n]{0,30}?(' + NUM + r')', r'net worth[^\n]{0,30}?(' + NUM + r')'],
        "reserves_surplus":   [r'reserves and surplus[^\n]{0,30}?(' + NUM + r')', r'reserves & surplus[^\n]{0,30}?(' + NUM + r')'],
        "total_borrowings":   [r'total borrowings[^\n]{0,30}?(' + NUM + r')', r'total debt[^\n]{0,30}?(' + NUM + r')'],
        "long_term_borrowings":[r'long[- ]term borrowings[^\n]{0,30}?(' + NUM + r')'],
        "short_term_borrowings":[r'short[- ]term borrowings[^\n]{0,30}?(' + NUM + r')'],
        "current_liabilities":[r'total current liabilities[^\n]{0,30}?(' + NUM + r')', r'current liabilities[^\n]{0,30}?(' + NUM + r')'],
        "total_liabilities":  [r'total liabilities[^\n]{0,30}?(' + NUM + r')'],
        "operating_cash_flow":[r'(?:net )?cash (?:from|generated (?:from|by)) operating[^\n]{0,30}?(' + NUM + r')', r'operating cash flow[^\n]{0,30}?(' + NUM + r')'],
        "investing_cash_flow":[r'cash (?:from|used in) investing[^\n]{0,30}?(' + NUM + r')'],
        "financing_cash_flow":[r'cash (?:from|used in) financing[^\n]{0,30}?(' + NUM + r')'],
        "capex":              [r'capital expenditure[^\n]{0,30}?(' + NUM + r')', r'purchase of (?:property|fixed assets|ppe)[^\n]{0,30}?(' + NUM + r')', r'\bcapex\b[^\n]{0,30}?(' + NUM + r')'],
        "current_ratio":      [r'current ratio[^\n]{0,30}?(' + NUM + r')'],
        "debt_equity_ratio":  [r'debt[- /](?:to[- ])?equity[^\n]{0,30}?(' + NUM + r')', r'd/e ratio[^\n]{0,30}?(' + NUM + r')'],
        "interest_coverage":  [r'interest coverage[^\n]{0,30}?(' + NUM + r')', r'interest cover[^\n]{0,30}?(' + NUM + r')'],
        "roe":                [r'return on equity[^\n]{0,30}?(' + NUM + r')', r'\broe\b[^\n]{0,30}?(' + NUM + r')'],
        "roa":                [r'return on assets[^\n]{0,30}?(' + NUM + r')', r'\broa\b[^\n]{0,30}?(' + NUM + r')'],
        "roce":               [r'return on capital employed[^\n]{0,30}?(' + NUM + r')', r'\broce\b[^\n]{0,30}?(' + NUM + r')'],
    }

    t_lower = text.lower()
    for metric, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, t_lower)
            if m:
                metrics[metric] = m.group(1)
                break

    return dict(metrics)


# ─── AI PROVIDER FUNCTIONS ───────────────────────────────────────────────────

def _sync_gemini(text: str) -> dict:
    """
    Google Gemini — primary AI provider.
    Uses gemini-2.0-flash first, falls back through flash and pro variants.
    """
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not configured")

    models = [
        ("gemini-2.0-flash",             44000, False),  # Primary — best speed/quality
        ("gemini-2.0-flash-lite",        44000, False),  # Faster fallback
        ("gemini-2.5-flash-preview-04-17", 44000, False), # Most capable
        ("gemini-2.0-flash-exp",         20000, True),   # Experimental lean fallback
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
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 16384,
                    },
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
                        logger.info("Gemini %s: received %d chars", model, len(raw))
                        return safe_parse_json(raw)
                    logger.warning("Gemini %s: empty response", model)
                else:
                    last_error = f"No candidates: {body.get('promptFeedback', '')}"
                    logger.warning("Gemini %s: %s", model, last_error)
                continue

            if resp.status_code == 429:
                last_error = "Rate limited (429)"
                logger.warning("Gemini %s rate limited, trying next model", model)
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            logger.warning("Gemini %s: %s", model, last_error)

        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
            logger.warning("Gemini %s timed out", model)
            continue
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning("Gemini %s error: %s", model, last_error)
            continue

    raise Exception(f"All Gemini models failed. Last: {last_error}")


def _sync_groq(text: str) -> dict:
    """
    Groq — ultra-fast inference, free tier.
    """
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY not configured")

    models = [
        ("llama-3.3-70b-versatile",        20000, False),  # Working — reduced size to avoid 413
        ("llama-3.1-8b-instant",           14000, True),   # Working lean
        ("llama3-groq-70b-8192-tool-use-preview", 14000, True),  # Working
        ("llama3-groq-8b-8192-tool-use-preview",  14000, True),  # Working lean
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
            logger.info("Groq %s: HTTP %d", model, resp.status_code)

            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                if raw:
                    logger.info("Groq %s: received %d chars", model, len(raw))
                    return safe_parse_json(raw)
                logger.warning("Groq %s: empty response", model)
                continue

            if resp.status_code == 429:
                last_error = "Rate limited (429)"
                logger.warning("Groq %s rate limited, trying next model", model)
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            logger.warning("Groq %s: %s", model, last_error)

        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
            logger.warning("Groq %s timed out", model)
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning("Groq %s error: %s", model, last_error)

    raise Exception(f"All Groq models failed. Last: {last_error}")


def _sync_together(text: str) -> dict:
    """
    Together AI — strong open models with generous free tier.
    """
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
            logger.info("Together %s: sending %d chars", model, len(prompt))
            resp = requests.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 16384,
                    "temperature": 0.1,
                },
                timeout=120,
            )
            logger.info("Together %s: HTTP %d", model, resp.status_code)

            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                if raw:
                    logger.info("Together %s: received %d chars", model, len(raw))
                    return safe_parse_json(raw)
                logger.warning("Together %s: empty response", model)
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            logger.warning("Together %s: %s", model, last_error)

        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
            logger.warning("Together %s timed out", model)
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning("Together %s error: %s", model, last_error)

    raise Exception(f"All Together models failed. Last: {last_error}")


def _sync_openrouter(text: str) -> dict:
    """
    OpenRouter — routes to multiple providers with generous free tier.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise Exception("OPENROUTER_API_KEY not configured")

    models = [
        ("meta-llama/llama-3.3-70b-instruct", 44000, False),
        ("meta-llama/llama-3.1-70b-instruct", 44000, False),
        ("google/gemma-2-27b-it",             20000, True),
        ("mistralai/mistral-7b-instruct",     20000, True),
    ]

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            logger.info("OpenRouter %s: sending %d chars", model, len(prompt))
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://finsight-vert.vercel.app",
                    "X-Title": "FinSight",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 16384,
                    "temperature": 0.1,
                },
                timeout=120,
            )
            logger.info("OpenRouter %s: HTTP %d", model, resp.status_code)

            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                if raw:
                    logger.info("OpenRouter %s: received %d chars", model, len(raw))
                    return safe_parse_json(raw)
                logger.warning("OpenRouter %s: empty response", model)
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            logger.warning("OpenRouter %s: %s", model, last_error)

        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
            logger.warning("OpenRouter %s timed out", model)
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning("OpenRouter %s error: %s", model, last_error)

    raise Exception(f"All OpenRouter models failed. Last: {last_error}")


def _sync_cloudflare(text: str) -> dict:
    """
    Cloudflare Workers AI — free 10,000 requests/day, no rate limiting issues.
    """
    cf_account = os.getenv("CF_ACCOUNT_ID", "")
    cf_token   = os.getenv("CF_API_TOKEN", "")
    if not cf_account or not cf_token:
        raise Exception("CF_ACCOUNT_ID or CF_API_TOKEN not configured")

    models = [
        ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", 12000, False),  # 24k ctx, 13k input safe
        ("@cf/meta/llama-3.1-8b-instruct-fast",       10000, True),   # 24k ctx, lean only
        ("@cf/mistral/mistral-7b-instruct-v0.2-lora",  8000, True),   # 15k ctx, small only
    ]

    headers = {
        "Authorization": f"Bearer {cf_token}",
        "Content-Type": "application/json",
    }

    last_error = "unknown"
    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run/{model}"
            logger.info("Cloudflare %s: sending %d chars", model, len(prompt))
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 16384,
                    "temperature": 0.1,
                },
                timeout=120,
            )
            logger.info("Cloudflare %s: HTTP %d", model, resp.status_code)

            if resp.status_code == 200:
                body = resp.json()
                if body.get("success"):
                    raw = body.get("result", {}).get("response", "")
                    if raw:
                        logger.info("Cloudflare %s: received %d chars", model, len(raw))
                        return safe_parse_json(raw)
                    logger.warning("Cloudflare %s: empty response", model)
                else:
                    errors = body.get("errors", [])
                    last_error = str(errors)[:200]
                    logger.warning("Cloudflare %s: API error: %s", model, last_error)
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            logger.warning("Cloudflare %s: %s", model, last_error)

        except requests.exceptions.Timeout:
            last_error = "Timeout after 120s"
            logger.warning("Cloudflare %s timed out", model)
            continue
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning("Cloudflare %s error: %s", model, last_error)
            continue

    raise Exception(f"All Cloudflare models failed. Last: {last_error}")


# ─── MAIN ANALYSIS ORCHESTRATOR ──────────────────────────────────────────────
# ─── FMP ANALYSIS ENRICHMENT ─────────────────────────────────────────────────

def _detect_ticker_from_text(text: str) -> str | None:
    """Detect NSE ticker from financial document text. Strict to avoid false positives."""
    import re

    # Common false positives to ignore
    BLOCKLIST = {
        "THE", "AND", "FOR", "ITS", "ALL", "NEW", "OLD", "HUT", "MR", "DR",
        "MD", "CEO", "CFO", "CIO", "CTO", "COO", "BSE", "NSE", "SEC", "RBI",
        "GOI", "INR", "USD", "PDF", "FY", "QR", "AGM", "EGM", "ROE", "ROA",
        "PAT", "PBT", "EPS", "NAV", "NPA", "EMI", "GST", "TDS", "CIN", "DIN",
        "PAN", "TAN", "KYC", "MCA", "SEBI", "IRDAI", "RBI", "NCLT", "NCLAT",
    }

    t = text[:6000]

    # Strict patterns — only match explicit symbol declarations
    patterns = [
        r"NSE\s*(?:Symbol|Code|Scrip)?\s*[:\-]\s*([A-Z][A-Z0-9]{1,11})(?:\s|$|,|;)",
        r"BSE\s*(?:Symbol|Code|Scrip)?\s*[:\-]\s*([A-Z][A-Z0-9]{1,11})(?:\s|$|,|;)",
        r"(?:Stock|Trading|Scrip)\s*Symbol\s*[:\-]\s*([A-Z][A-Z0-9]{1,11})",
        r"Symbol\s*[:\-]\s*([A-Z][A-Z0-9]{1,11})(?:\s|$|,|\])",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            sym = m.group(1).strip().upper()
            if sym not in BLOCKLIST and 2 <= len(sym) <= 12:
                logger.info(f"Ticker from pattern: {sym}")
                return sym

    # Company name → known ticker mapping (curated, not broad regex)
    KNOWN = {
        "infosys limited": "INFY", "infosys ltd": "INFY", "infosys": "INFY",
        "tata consultancy services": "TCS", "tcs limited": "TCS",
        "wipro limited": "WIPRO", "wipro ltd": "WIPRO",
        "hcl technologies": "HCLTECH", "hcl tech": "HCLTECH",
        "reliance industries": "RELIANCE",
        "hdfc bank limited": "HDFCBANK", "hdfc bank": "HDFCBANK",
        "icici bank limited": "ICICIBANK", "icici bank": "ICICIBANK",
        "axis bank limited": "AXISBANK", "axis bank": "AXISBANK",
        "kotak mahindra bank": "KOTAKBANK",
        "state bank of india": "SBIN",
        "maruti suzuki": "MARUTI",
        "bajaj finance limited": "BAJFINANCE",
        "bajaj finserv": "BAJAJFINSV",
        "asian paints limited": "ASIANPAINT",
        "hindustan unilever": "HINDUNILVR",
        "itc limited": "ITC",
        "larsen & toubro": "LT", "l&t limited": "LT",
        "tech mahindra": "TECHM",
        "sun pharmaceutical": "SUNPHARMA",
        "dr. reddy's": "DRREDDY", "dr reddys": "DRREDDY",
        "cipla limited": "CIPLA",
        "titan company": "TITAN",
        "tata motors limited": "TATAMOTORS",
        "tata steel limited": "TATASTEEL",
        "ultratech cement": "ULTRACEMCO",
        "nestle india": "NESTLEIND",
        "power grid corporation": "POWERGRID",
        "ntpc limited": "NTPC",
        "oil and natural gas": "ONGC",
        "coal india limited": "COALINDIA",
        "bharat petroleum": "BPCL",
        "indian oil corporation": "IOC",
        "hindalco industries": "HINDALCO",
        "jsw steel": "JSWSTEEL",
        "grasim industries": "GRASIM",
        "avenue supermarts": "DMART",
        "apollo hospitals": "APOLLOHOSP",
        "divi's laboratories": "DIVISLAB",
        "divis laboratories": "DIVISLAB",
        "adani enterprises": "ADANIENT",
        "adani ports": "ADANIPORTS",
        "tata consumer": "TATACONSUM",
        "bajaj auto": "BAJAJ-AUTO",
        "hero motocorp": "HEROMOTOCO",
        "eicher motors": "EICHERMOT",
        "mahindra & mahindra": "M&M",
        "britannia industries": "BRITANNIA",
        "pidilite industries": "PIDILITIND",
        "havells india": "HAVELLS",
        "voltas limited": "VOLTAS",
        "muthoot finance": "MUTHOOTFIN",
        "shree cement": "SHREECEM",
        "dlf limited": "DLF",
        "godrej consumer": "GODREJCP",
        "marico limited": "MARICO",
        "dabur india": "DABUR",
        "emami limited": "EMAMILTD",
        "page industries": "PAGEIND",
    }
    t_lower = text[:4000].lower()
    for name, ticker in KNOWN.items():
        if name in t_lower:
            logger.info(f"Ticker from company name '{name}': {ticker}")
            return ticker

    return None


def _fmp_data_to_text(d: dict) -> str:
    """Format FMP data into clean text for AI prompt enrichment."""
    lines = []
    if d.get("quote"):
        q = d["quote"]
        lines += [
            "LIVE MARKET DATA (Financial Modeling Prep — use for valuation context):",
            f"  Current Price:    {q.get('price', 'N/A')}  |  Market Cap: {q.get('marketCap', 'N/A')}",
            f"  52w High/Low:     {q.get('yearHigh', 'N/A')} / {q.get('yearLow', 'N/A')}",
            f"  P/E Ratio (TTM):  {q.get('pe', 'N/A')}x  |  EPS: {q.get('eps', 'N/A')}",
            f"  Beta:             {q.get('beta', 'N/A')}  |  Div Yield: {q.get('dividendYield', 'N/A')}%",
            "",
        ]
    if d.get("profile"):
        p = d["profile"]
        lines += [
            "COMPANY PROFILE:",
            f"  Sector: {p.get('sector', 'N/A')}  |  Industry: {p.get('industry', 'N/A')}",
            f"  Employees: {p.get('fullTimeEmployees', 'N/A')}  |  CEO: {p.get('ceo', 'N/A')}",
            "",
        ]
    if d.get("ratios"):
        r = d["ratios"]
        lines += [
            "KEY RATIOS TTM (cross-validate with document figures):",
            f"  P/E: {r.get('peRatioTTM', 'N/A')}x  |  P/B: {r.get('priceToBookRatioTTM', 'N/A')}x  |  EV/EBITDA: {r.get('enterpriseValueMultipleTTM', 'N/A')}x",
            f"  ROE: {r.get('returnOnEquityTTM', 'N/A')}  |  ROA: {r.get('returnOnAssetsTTM', 'N/A')}  |  Net Margin: {r.get('netProfitMarginTTM', 'N/A')}",
            f"  D/E: {r.get('debtEquityRatioTTM', 'N/A')}  |  Current Ratio: {r.get('currentRatioTTM', 'N/A')}  |  Div Yield: {r.get('dividendYieldTTM', 'N/A')}%",
            "",
        ]
    return "\n".join(lines)


async def _fmp_fetch_for_analysis(ticker: str) -> dict | None:
    """Fetch live FMP data for AI prompt enrichment. Tries plain, .NS, .BO variants."""
    try:
        sym = ticker.upper()
        candidates = [sym, f"{sym}.NS", f"{sym}.BO"]

        def safe_j(r):
            try:
                if isinstance(r, Exception): return None
                if r.status_code == 403:
                    logger.warning("FMP 403 — plan may not include this endpoint")
                    return None
                if r.status_code != 200: return None
                data = r.json()
                if isinstance(data, dict) and "Error Message" in data: return None
                return data[0] if isinstance(data, list) and data else (data if data else None)
            except Exception:
                return None

        for fmp_sym in candidates:
            async with httpx.AsyncClient(timeout=12) as c:
                results = await asyncio.gather(
                    c.get(f"{FMP_BASE}/v3/quote/{fmp_sym}", params={"apikey": FMP_API_KEY}),
                    c.get(f"{FMP_BASE}/v3/profile/{fmp_sym}", params={"apikey": FMP_API_KEY}),
                    c.get(f"{FMP_BASE}/v3/ratios-ttm/{fmp_sym}", params={"apikey": FMP_API_KEY}),
                    return_exceptions=True,
                )
            q, p, r = safe_j(results[0]), safe_j(results[1]), safe_j(results[2])
            if q or p:
                logger.info(f"FMP OK: {fmp_sym} — quote={bool(q)}, profile={bool(p)}, ratios={bool(r)}")
                return {"quote": q, "profile": p, "ratios": r}

        logger.warning(f"FMP: no data found for any variant of {sym}")
        return None

    except Exception as e:
        logger.warning(f"FMP enrichment error (non-fatal): {e}")
        return None


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
            f"(found only: {found_kw}). "
            f"Please verify the PDF is a financial results document. "
            f"Text preview: {full_text[:200]}"
        )

    logger.info(f"Analysis starting — text: {len(full_text):,} chars, keywords found: {found_kw}")

    loop   = asyncio.get_event_loop()
    errors = []

    metrics = _extract_metrics_from_text(full_text)
    ratios  = compute_financial_ratios(metrics)
    logger.info(f"Text-based metrics: {metrics}")
    logger.info(f"Computed ratios: {ratios}")

    metrics_block = ""
    if any(metrics.values()):
        metrics_block = f"""
REGEX-EXTRACTED HINTS (TREAT WITH CAUTION — may contain errors from wrong table rows):
These are regex-extracted numbers. They may be wrong due to unit mismatches or wrong row matches.
DO NOT trust these blindly. Always verify against the actual tables in the document below.
Use only as a starting-point cross-reference:
{json.dumps(metrics, indent=2)}

COMPUTED RATIOS (derived from above hints — verify independently):
{json.dumps(ratios, indent=2)}

IMPORTANT: If the document tables show different numbers, ALWAYS use the document tables.
The regex hints above are frequently wrong on Indian quarterly filings due to mixed units.

"""

    # ── FMP live enrichment ──────────────────────────────────────────────────
    fmp_block = ""
    if FMP_API_KEY:
        try:
            ticker = _detect_ticker_from_text(full_text)
            if ticker:
                fmp_data = await _fmp_fetch_for_analysis(ticker)
                if fmp_data:
                    fmp_block = (
                        "\n\n━━━ LIVE MARKET DATA (Financial Modeling Prep) ━━━\n"
                        + _fmp_data_to_text(fmp_data)
                        + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    )
                    logger.info(f"FMP enrichment injected ({len(fmp_block)} chars) for {ticker}")
        except Exception as fmp_err:
            logger.warning(f"FMP enrichment skipped (non-fatal): {fmp_err}")

    enhanced_text = fmp_block + metrics_block + full_text

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
            logger.info(f"Trying {provider_name} with {len(enhanced_text):,} chars...")
            result = await loop.run_in_executor(executor, func, enhanced_text)
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
_FMP_CACHE_TTL   = 300  # 5 minutes

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
        logger.info(f"FMP cache hit: {sym}")
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
        data = await _fmp_get(f"/v3/historical-price-full/{fmp_sym}",
                              {"timeseries": period_map[period]})
        records = []
        for d in (data.get("historical") or []):
            records.append({
                "date":   d.get("date"),
                "open":   _safe(d.get("open")),
                "high":   _safe(d.get("high")),
                "low":    _safe(d.get("low")),
                "close":  _safe(d.get("close")),
                "volume": d.get("volume"),
            })
        result = {
            "symbol": sym, "fmp_symbol": fmp_sym,
            "period": period, "count": len(records),
            "data": records,
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }
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
        result = {
            "symbol": sym, "fmp_symbol": fmp_sym,
            "source": "Financial Modeling Prep",
            "income_statement": income or [],
            "balance_sheet":    balance or [],
            "cash_flow":        cashflow or [],
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }
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

    return {"count": len(results), "results": results,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


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
        try:
            return await get_fmp_quote(sym)
        except Exception:
            return None

    results = await asyncio.gather(*[_safe_quote(s) for s in NIFTY50])
    quotes  = [r for r in results if r and r.get("day_change_pct") is not None]
    quotes.sort(key=lambda x: x.get("day_change_pct", 0), reverse=True)

    gainers = [{"symbol": q["symbol"], "name": q["company_name"],
                "price": q["price"], "change_pct": q["day_change_pct"]}
               for q in quotes[:5]]
    losers  = [{"symbol": q["symbol"], "name": q["company_name"],
                "price": q["price"], "change_pct": q["day_change_pct"]}
               for q in quotes[-5:][::-1]]

    result = {"gainers": gainers, "losers": losers, "universe": "Nifty 50",
              "fetched_at": datetime.utcnow().isoformat() + "Z"}
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
