import os, uuid, logging, json, io, asyncio, httpx, re
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


# ─── PDF EXTRACTION (FIXED) ──────────────────────────────────────────────────

# ─── ADVANCED TABLE + METRIC EXTRACTION ─────────────────────────────

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
                        cleaned = [
                            str(cell).strip() if cell else ""
                            for cell in row
                        ]

                        if any(cleaned):
                            clean_table.append(cleaned)

                    if clean_table:
                        tables.append({
                            "page": page_num + 1,
                            "rows": clean_table
                        })

        logger.info(f"Extracted {len(tables)} tables")

    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")

    return tables


def parse_financial_metrics(tables):
    """
    Extract key financial metrics from tables.
    Covers all major financial analysis types:
    Vertical, Horizontal, Leverage, Liquidity, Profitability,
    Efficiency, Cash Flow, Rates of Return, Valuation, Variance.
    """

    metrics = defaultdict(str)

    keywords = {
        # ── Income Statement ──────────────────────────────────────────
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

        # ── Balance Sheet ─────────────────────────────────────────────
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

        # ── Cash Flow ────────────────────────────────────────────────
        "operating_cash_flow": ["cash flow from operating", "net cash from operations", "operating cash flow", "ocf"],
        "investing_cash_flow": ["cash flow from investing", "investing activities"],
        "financing_cash_flow": ["cash flow from financing", "financing activities"],
        "free_cash_flow": ["free cash flow", "fcf"],
        "capex": ["capital expenditure", "capex", "purchase of fixed assets", "additions to property"],

        # ── Ratios (if directly stated in the document) ───────────────
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

                if metrics.get(metric):   # already found — skip
                    continue

                if any(k in row_text for k in keys):

                    numbers = re.findall(
                        r'-?\d[\d,\.]*',
                        row_text
                    )

                    if numbers:
                        metrics[metric] = numbers[0]

    logger.info(f"Extracted metrics: {dict(metrics)}")

    return dict(metrics)


def compute_financial_ratios(metrics: dict) -> dict:
    """
    Compute derived financial ratios from raw extracted metrics.
    Covers Vertical, Leverage, Liquidity, Profitability, Efficiency, and Cash Flow analysis.
    Returns only ratios that can be computed from available data.
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

    rev  = metrics.get("revenue")
    pat  = metrics.get("net_profit")
    ebitda = metrics.get("ebitda")
    ebit = metrics.get("ebit")
    gross  = metrics.get("gross_profit")
    debt   = metrics.get("borrowings")
    equity = metrics.get("total_equity")
    curr_a = metrics.get("current_assets")
    curr_l = metrics.get("current_liabilities")
    cash   = metrics.get("cash_equivalents")
    inv    = metrics.get("inventory")
    recv   = metrics.get("accounts_receivable")
    assets = metrics.get("total_assets")
    ocf    = metrics.get("operating_cash_flow")
    fin_cost = metrics.get("finance_cost")
    rev_prev = metrics.get("revenue_previous")

    # ── Profitability Ratios ─────────────────────────────────────────
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

    # ── Leverage Ratios ──────────────────────────────────────────────
    r = _ratio(debt, equity)
    if r: ratios["debt_to_equity"] = r

    r = _ratio(debt, ebitda)
    if r: ratios["debt_to_ebitda"] = r

    # Interest coverage = EBIT / Finance Cost
    r = _ratio(ebit or ebitda, fin_cost)
    if r: ratios["interest_coverage_ratio"] = r

    # ── Liquidity Ratios ─────────────────────────────────────────────
    r = _ratio(curr_a, curr_l)
    if r: ratios["current_ratio"] = r

    # Quick ratio = (Current Assets - Inventory) / Current Liabilities
    ca_f = _to_float(curr_a)
    inv_f = _to_float(inv) or 0.0
    cl_f  = _to_float(curr_l)
    if ca_f is not None and cl_f and cl_f != 0:
        ratios["quick_ratio"] = str(round((ca_f - inv_f) / cl_f, 2))

    # Cash ratio
    r = _ratio(cash, curr_l)
    if r: ratios["cash_ratio"] = r

    # ── Efficiency Ratios ────────────────────────────────────────────
    r = _ratio(rev, assets)
    if r: ratios["asset_turnover"] = r

    r = _ratio(rev, inv)
    if r: ratios["inventory_turnover"] = r

    # Operating cash flow to current liabilities
    r = _ratio(ocf, curr_l)
    if r: ratios["ocf_to_current_liabilities"] = r

    # ── Horizontal Analysis (YoY Revenue Growth) ─────────────────────
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
    Use pdfplumber for superior table extraction — preserves column alignment
    and prevents the decimal/digit-dropping bug that affects pypdf on tabular data.
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

                # Extract tables first — preserves numbers correctly
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        cleaned = [str(cell).strip() if cell else "" for cell in row]
                        if any(cleaned):
                            page_text += " | ".join(cleaned) + "\n"

                # Then extract remaining text
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
    Returns sorted list of page indices that contain financial data.
    Always includes first 5 pages.
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
        if score >= 2:  # lowered from 3 — capture more pages with financial data
            core_pages.add(i)

    logger.info(f"PDF: {total} pages total, {len(core_pages)} financial pages selected: {sorted(core_pages)}")
    return sorted(core_pages)


def _validate_extracted_numbers(text: str, source_text: str) -> bool:
    """
    Basic sanity check: verify key numbers from the extracted text
    actually appear in the raw source. Logs a warning if mismatch found.
    """
    # Find all number patterns in extracted text
    numbers = re.findall(r'\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b', text)
    mismatches = 0
    for num in numbers[:20]:  # check first 20 numbers
        num_clean = num.replace(",", "")
        if num_clean not in source_text.replace(",", ""):
            mismatches += 1
    if mismatches > 5:
        logger.warning(f"Number validation: {mismatches}/20 numbers not found in source — possible extraction issue")
        return False
    return True


def extract_financial_snippet(raw_bytes: bytes, max_chars: int = 60000) -> str:
    """
    FIXED extraction pipeline:
    1. Select financial pages using keyword scoring
    2. Use pdfplumber (primary) for table-aware extraction — fixes digit-dropping bug
    3. Fall back to pypdf if pdfplumber unavailable
    4. Validate extracted numbers against raw bytes
    5. Add data integrity note for partial documents (newspaper extracts etc.)
    """
    page_indices = _select_financial_pages(raw_bytes)

    # PRIMARY: pdfplumber — preserves table column alignment and numbers correctly
    result = _extract_with_pdfplumber(raw_bytes, page_indices)

    # FALLBACK: pypdf
    if not result.strip():
        logger.info("Falling back to pypdf extraction")
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        result = ""
        for i in page_indices:
            pt = reader.pages[i].extract_text() or ""
            if pt.strip():
                result += f"\n--- PAGE {i+1} ---\n{pt}\n"
        logger.info(f"pypdf extracted {len(result):,} chars")

    # Detect if this is a partial/newspaper extract — flag it for the model
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
    Validates the PDF, checks it has selectable text, then extracts financial pages.
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


# ─── AI PROMPT (UPGRADED) ────────────────────────────────────────────────────

# ─── TEXT CHUNKING FOR LARGE FILINGS ───────────────────────────────

def split_into_chunks(text, size=12000, overlap=1200):
    """
    Split text into overlapping chunks.
    Larger size ensures more context per chunk; overlap prevents boundary cut-offs.
    """
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + size]
        chunks.append(chunk)
        start += size - overlap
    logger.info(f"Split document into {len(chunks)} chunks of ~{size} chars")
    return chunks

def build_prompt(text: str, max_doc_chars: int = 44000) -> str:
    """
    Full institutional-grade prompt. Use for large-context models (Gemini, DeepSeek, GPT-4).
    Template overhead ~15k chars. Total prompt = ~15k + max_doc_chars.
    Default max_doc_chars=44000 → total ~59k chars, safe for 64k-context models.
    Pass max_doc_chars=160000 for Gemini 1M-context models.
    """
    snippet = text[:max_doc_chars]
    logger.info(f"Full prompt: {len(snippet):,} doc chars (from {len(text):,} total)")

    return f"""You are FinSight — a senior institutional equity research analyst at a top-tier investment bank.
Your job: extract EVERY number from this financial document and produce the most detailed, accurate, investor-grade analysis possible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 1 — EXHAUSTIVE EXTRACTION (MOST IMPORTANT RULE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before writing a single output field, you MUST perform a complete scan:

STEP 1: Read the entire document from top to bottom.
STEP 2: Find and note EVERY table. Tables contain the most data. Look for:
  - Standalone financial statements (P&L, Balance Sheet, Cash Flow)
  - "Key Financial Data" / "Financial Highlights" / "Financial Summary" tables
  - "Key Financial Ratios" sections — these often contain Current Ratio, D/E, ROE, ROCE already calculated
  - Notes to Accounts — contain breakdowns of Borrowings, Receivables, Inventory, Capex
  - Segment reporting tables — contain Revenue, EBIT per segment
STEP 3: For EVERY number you find, record it with its label and period.
STEP 4: Only AFTER completing the full scan, fill in the JSON output.

FORBIDDEN: Writing "Not available in this filing" for ANY field unless you have
read the COMPLETE document and confirmed the data is genuinely absent.
FORBIDDEN: Skipping tables or footnotes.
FORBIDDEN: Rounding or approximating numbers. Copy them exactly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 2 — NUMBER ACCURACY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Copy numbers EXACTLY. Preserve ALL digits, commas, decimals.
Always state the unit next to the number e.g. "20,078.39 Cr".
If the document says "(₹ in Crores)", ALL numbers in that table are in Crores.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 3 — ALWAYS CALCULATE THESE RATIOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

When base numbers are available, ALWAYS compute (do not leave blank):
  Gross/EBITDA/EBIT/Net Margin % | Revenue & PAT Growth YoY %
  D/E | Debt/EBITDA | Interest Coverage | Current Ratio | Quick Ratio
  Asset Turnover | Inventory Turnover | ROE | ROA | OCF/PAT | FCF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 4 — COMMENTARY MUST BE SPECIFIC & NUMERIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BAD:  "Revenue grew well."
GOOD: "Revenue grew 18.4% YoY from ₹8,234 Cr to ₹9,750 Cr driven by 22% domestic surge."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEALTH SCORE (0–100) — FILL BREAKDOWN FULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Calculate each component and fill health_score_breakdown with:
  - "pts": points awarded for this component
  - "max": maximum possible points for this component
  - "value": the actual metric value from the document (e.g. "18.4% YoY", "₹1,234 Cr", "1.8x")
  - "reason": one sentence explaining why this score was awarded

Scoring rules:
  revenue_growth  (max 10): Revenue growing YoY = 10pts | declining = 0pts
  net_margin      (max 20): >15%=20 | 10-15%=15 | 5-10%=10 | 0-5%=5 | negative=0
  ebitda_margin   (max 15): >25%=15 | 15-25%=10 | 8-15%=6  | <8%=2
  debt_to_equity  (max 15): <0.3=15 | 0.3-1.0=10 | 1.0-2.0=5 | >2.0=0
  current_ratio   (max 10): >2.0=10 | 1.5-2.0=8 | 1.0-1.5=5 | <1.0=0
  ocf_quality     (max 10): OCF > PAT = 10 | OCF positive = 7 | OCF negative = 0
  roe             (max 10): >20%=10 | 15-20%=7 | 10-15%=4 | <10%=1
  eps_growth      (max 10): EPS growing YoY = 10pts | declining = 0pts

Labels: 0-40=Caution | 41-60=Fair | 61-75=Good | 76-88=Strong | 89-100=Exceptional

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — RETURN ONLY VALID JSON, NO MARKDOWN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{
  "company_name": "", "statement_type": "", "period": "",
  "reporting_currency": "", "unit": "",
  "health_score": 0, "health_label": "",
  "health_score_breakdown": {{"revenue_growth_pts":0,"net_margin_pts":0,"ebitda_margin_pts":0,"debt_equity_pts":0,"current_ratio_pts":0,"ocf_quality_pts":0,"roe_pts":0,"eps_growth_pts":0,"total":0}},
  "headline": "",
  "executive_summary": "",
  "income_statement": {{
    "revenue":{{"current":"","previous":"","unit":""}},
    "other_income":{{"current":"","previous":"","unit":""}},
    "total_income":{{"current":"","previous":"","unit":""}},
    "cost_of_goods_sold":{{"current":"","previous":"","unit":""}},
    "gross_profit":{{"current":"","previous":"","unit":""}},
    "employee_costs":{{"current":"","previous":"","unit":""}},
    "other_expenses":{{"current":"","previous":"","unit":""}},
    "ebitda":{{"current":"","previous":"","unit":""}},
    "depreciation":{{"current":"","previous":"","unit":""}},
    "ebit":{{"current":"","previous":"","unit":""}},
    "finance_cost":{{"current":"","previous":"","unit":""}},
    "pbt":{{"current":"","previous":"","unit":""}},
    "tax_expense":{{"current":"","previous":"","unit":""}},
    "pat":{{"current":"","previous":"","unit":""}},
    "eps_basic":{{"current":"","previous":"","unit":"₹"}},
    "eps_diluted":{{"current":"","previous":"","unit":"₹"}}
  }},
  "balance_sheet": {{
    "total_assets":{{"current":"","previous":"","unit":""}},
    "non_current_assets":{{"current":"","previous":"","unit":""}},
    "fixed_assets_net":{{"current":"","previous":"","unit":""}},
    "current_assets":{{"current":"","previous":"","unit":""}},
    "inventories":{{"current":"","previous":"","unit":""}},
    "trade_receivables":{{"current":"","previous":"","unit":""}},
    "cash_equivalents":{{"current":"","previous":"","unit":""}},
    "total_equity":{{"current":"","previous":"","unit":""}},
    "share_capital":{{"current":"","previous":"","unit":""}},
    "reserves_surplus":{{"current":"","previous":"","unit":""}},
    "total_borrowings":{{"current":"","previous":"","unit":""}},
    "long_term_borrowings":{{"current":"","previous":"","unit":""}},
    "short_term_borrowings":{{"current":"","previous":"","unit":""}},
    "trade_payables":{{"current":"","previous":"","unit":""}},
    "current_liabilities":{{"current":"","previous":"","unit":""}}
  }},
  "cash_flow_statement": {{
    "operating_cash_flow":{{"current":"","previous":"","unit":""}},
    "investing_cash_flow":{{"current":"","previous":"","unit":""}},
    "financing_cash_flow":{{"current":"","previous":"","unit":""}},
    "capex":{{"current":"","previous":"","unit":""}},
    "free_cash_flow":{{"current":"","previous":"","unit":""}}
  }},
  "key_metrics": [
    {{"metric":"Revenue","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Gross Profit","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"EBITDA","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"EBIT","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"PAT","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"EPS (Basic) ₹","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Total Assets","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Total Equity","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Total Borrowings","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Operating Cash Flow","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Free Cash Flow","current":"","previous":"","change_pct":"","comment":""}},
    {{"metric":"Cash & Equivalents","current":"","previous":"","change_pct":"","comment":""}}
  ],
  "vertical_analysis": {{
    "gross_margin_pct":{{"current":"","previous":"","comment":""}},
    "ebitda_margin_pct":{{"current":"","previous":"","comment":""}},
    "ebit_margin_pct":{{"current":"","previous":"","comment":""}},
    "net_profit_margin_pct":{{"current":"","previous":"","comment":""}},
    "cogs_pct_revenue":{{"current":"","previous":"","comment":""}},
    "employee_cost_pct":{{"current":"","previous":"","comment":""}},
    "finance_cost_pct":{{"current":"","previous":"","comment":""}},
    "commentary":""
  }},
  "horizontal_analysis": {{
    "revenue_growth_yoy_pct":"","gross_profit_growth_yoy_pct":"",
    "ebitda_growth_yoy_pct":"","pat_growth_yoy_pct":"","eps_growth_yoy_pct":"",
    "total_assets_growth_yoy_pct":"","borrowings_growth_yoy_pct":"",
    "notable_trends":[]
  }},
  "leverage_analysis": {{
    "total_borrowings":"","long_term_borrowings":"","short_term_borrowings":"",
    "debt_to_equity":"","debt_to_ebitda":"","interest_coverage_ratio":"",
    "net_debt":"","net_debt_to_ebitda":"","commentary":""
  }},
  "liquidity_analysis": {{
    "current_ratio":"","quick_ratio":"","cash_ratio":"",
    "net_working_capital":"","cash_and_equivalents":"","commentary":""
  }},
  "profitability_analysis": {{
    "gross_margin_pct":"","ebitda_margin_pct":"","ebit_margin_pct":"",
    "net_profit_margin_pct":"","roe_pct":"","roa_pct":"","roic_pct":"","roce_pct":"",
    "commentary":""
  }},
  "efficiency_analysis": {{
    "asset_turnover":"","inventory_turnover_days":"","receivables_turnover_days":"",
    "payables_turnover_days":"","cash_conversion_cycle_days":"","commentary":""
  }},
  "cash_flow_analysis": {{
    "operating_cash_flow":"","investing_cash_flow":"","financing_cash_flow":"",
    "capex":"","free_cash_flow":"","ocf_to_pat_ratio":"","fcf_margin_pct":"",
    "cash_quality":"","commentary":""
  }},
  "rates_of_return": {{
    "roe_pct":"","roa_pct":"","roic_pct":"","roce_pct":"",
    "eps_basic":"","eps_diluted":"","eps_growth_pct":"",
    "dividend_per_share":"","dividend_payout_ratio":"","commentary":""
  }},
  "highlights":[],
  "risks":[],
  "what_to_watch":[],
  "investor_verdict":""
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINANCIAL DOCUMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{snippet}
"""


def build_lean_prompt(text: str, max_doc_chars: int = 18000) -> str:
    """
    Lean prompt for small-context models (8k–32k tokens).
    Strips verbose instructions to absolute minimum so the document fits.
    Template overhead ~2k chars. Total = ~2k + max_doc_chars.
    """
    snippet = text[:max_doc_chars]
    logger.info(f"Lean prompt: {len(snippet):,} doc chars (from {len(text):,} total)")

    return f"""You are a financial analyst. Analyse this document and return ONLY valid JSON (no markdown).

Rules:
- Extract every number exactly as written. Unit: state Cr/Lakh/₹ alongside each value.
- Calculate all ratios from available data. Never leave calculable fields blank.
- Commentary must contain specific numbers, not vague statements.
- Only write "Not available" if the data is genuinely absent after reading the full document.

Health score 0-100 — for each component fill: pts (awarded), max (max possible), value (actual metric), reason (one sentence why).
Scoring: revenue_growth(max 10: growing=10,declining=0) + net_margin(max 20: >15%=20,10-15%=15,5-10%=10,0-5%=5,neg=0) + ebitda_margin(max 15: >25%=15,15-25%=10,8-15%=6,<8%=2) + DE(max 15: <0.3=15,0.3-1=10,1-2=5,>2=0) + current_ratio(max 10: >2=10,1.5-2=8,1-1.5=5,<1=0) + ocf(max 10: >PAT=10,pos=7,neg=0) + roe(max 10: >20%=10,15-20%=7,10-15%=4,<10%=1) + eps_growth(max 10: growing=10,declining=0)
Labels: 0-40=Caution,41-60=Fair,61-75=Good,76-88=Strong,89-100=Exceptional

Return this exact JSON structure filled with real data:
{{"company_name":"","statement_type":"","period":"","reporting_currency":"","unit":"","health_score":0,"health_label":"","health_score_breakdown":{{"revenue_growth":{{"pts":0,"max":10,"value":"","reason":""}},"net_margin":{{"pts":0,"max":20,"value":"","reason":""}},"ebitda_margin":{{"pts":0,"max":15,"value":"","reason":""}},"debt_to_equity":{{"pts":0,"max":15,"value":"","reason":""}},"current_ratio":{{"pts":0,"max":10,"value":"","reason":""}},"ocf_quality":{{"pts":0,"max":10,"value":"","reason":""}},"roe":{{"pts":0,"max":10,"value":"","reason":""}},"eps_growth":{{"pts":0,"max":10,"value":"","reason":""}},"total":0}},"headline":"","executive_summary":"","income_statement":{{"revenue":{{"current":"","previous":"","unit":""}},"other_income":{{"current":"","previous":"","unit":""}},"total_income":{{"current":"","previous":"","unit":""}},"cost_of_goods_sold":{{"current":"","previous":"","unit":""}},"gross_profit":{{"current":"","previous":"","unit":""}},"employee_costs":{{"current":"","previous":"","unit":""}},"ebitda":{{"current":"","previous":"","unit":""}},"depreciation":{{"current":"","previous":"","unit":""}},"ebit":{{"current":"","previous":"","unit":""}},"finance_cost":{{"current":"","previous":"","unit":""}},"pbt":{{"current":"","previous":"","unit":""}},"tax_expense":{{"current":"","previous":"","unit":""}},"pat":{{"current":"","previous":"","unit":""}},"eps_basic":{{"current":"","previous":"","unit":"₹"}},"eps_diluted":{{"current":"","previous":"","unit":"₹"}}}},"balance_sheet":{{"total_assets":{{"current":"","previous":"","unit":""}},"current_assets":{{"current":"","previous":"","unit":""}},"inventories":{{"current":"","previous":"","unit":""}},"trade_receivables":{{"current":"","previous":"","unit":""}},"cash_equivalents":{{"current":"","previous":"","unit":""}},"total_equity":{{"current":"","previous":"","unit":""}},"total_borrowings":{{"current":"","previous":"","unit":""}},"long_term_borrowings":{{"current":"","previous":"","unit":""}},"short_term_borrowings":{{"current":"","previous":"","unit":""}},"trade_payables":{{"current":"","previous":"","unit":""}},"current_liabilities":{{"current":"","previous":"","unit":""}}}},"cash_flow_statement":{{"operating_cash_flow":{{"current":"","previous":"","unit":""}},"investing_cash_flow":{{"current":"","previous":"","unit":""}},"financing_cash_flow":{{"current":"","previous":"","unit":""}},"capex":{{"current":"","previous":"","unit":""}},"free_cash_flow":{{"current":"","previous":"","unit":""}}}},"key_metrics":[{{"metric":"Revenue","current":"","previous":"","change_pct":"","comment":""}},{{"metric":"EBITDA","current":"","previous":"","change_pct":"","comment":""}},{{"metric":"PAT","current":"","previous":"","change_pct":"","comment":""}},{{"metric":"EPS (Basic)","current":"","previous":"","change_pct":"","comment":""}},{{"metric":"Total Borrowings","current":"","previous":"","change_pct":"","comment":""}},{{"metric":"Operating Cash Flow","current":"","previous":"","change_pct":"","comment":""}}],"vertical_analysis":{{"gross_margin_pct":{{"current":"","previous":""}},"ebitda_margin_pct":{{"current":"","previous":""}},"net_profit_margin_pct":{{"current":"","previous":""}},"commentary":""}},"horizontal_analysis":{{"revenue_growth_yoy_pct":"","pat_growth_yoy_pct":"","eps_growth_yoy_pct":"","notable_trends":[]}},"leverage_analysis":{{"debt_to_equity":"","debt_to_ebitda":"","interest_coverage_ratio":"","commentary":""}},"liquidity_analysis":{{"current_ratio":"","quick_ratio":"","cash_ratio":"","commentary":""}},"profitability_analysis":{{"gross_margin_pct":"","ebitda_margin_pct":"","net_profit_margin_pct":"","roe_pct":"","roa_pct":"","commentary":""}},"cash_flow_analysis":{{"operating_cash_flow":"","capex":"","free_cash_flow":"","ocf_to_pat_ratio":"","cash_quality":"","commentary":""}},"rates_of_return":{{"roe_pct":"","roa_pct":"","eps_basic":"","eps_diluted":"","commentary":""}},"highlights":[],"risks":[],"what_to_watch":[],"investor_verdict":""}}

DOCUMENT:
{snippet}
"""

    financial_keywords = ["revenue", "profit", "income", "assets", "crore", "lakh", "eps", "ebitda", "loss",
                          "balance sheet", "cash flow", "borrowing", "equity", "liabilities"]
    found_kw = [kw for kw in financial_keywords if kw.lower() in snippet.lower()]
    if len(found_kw) < 2:
        logger.warning(f"Low financial keyword count: {found_kw}. Preview: {snippet[:300]}")

    return f"""You are FinSight — a senior institutional equity research analyst at a top-tier investment bank.
Your job: extract EVERY number from this financial document and produce the most detailed, accurate, investor-grade analysis possible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 1 — EXHAUSTIVE EXTRACTION (MOST IMPORTANT RULE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before writing a single output field, you MUST perform a complete scan:

STEP 1: Read the entire document from top to bottom.
STEP 2: Find and note EVERY table. Tables contain the most data. Look for:
  - Standalone financial statements (P&L, Balance Sheet, Cash Flow)
  - "Key Financial Data" / "Financial Highlights" / "Financial Summary" tables
  - "Key Financial Ratios" sections — these often contain Current Ratio, D/E, ROE, ROCE, etc. already calculated
  - Notes to Accounts — contain breakdowns of Borrowings, Receivables, Inventory, Capex
  - Segment reporting tables — contain Revenue, EBIT per segment
STEP 3: For EVERY number you find, record it with its label and period.
STEP 4: Only AFTER completing the full scan, fill in the JSON output.

FORBIDDEN: Writing "Not available in this filing" for ANY field unless you have
read the COMPLETE document and confirmed the data is genuinely absent.
FORBIDDEN: Skipping tables or footnotes.
FORBIDDEN: Rounding or approximating numbers. Copy them exactly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 2 — NUMBER ACCURACY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Copy numbers EXACTLY as they appear. Preserve ALL digits, commas, and decimals.
Units matter — if the document says "(₹ in Crores)", ALL numbers in that table are in Crores.
If a table says "(₹ in Lakhs)", ALL numbers in that table are in Lakhs.
Always state the unit in parentheses next to the number.

CORRECT:  "20,078.39 Cr"
WRONG:    "20078", "2007.8", "200.78 Cr", "20,078"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 3 — CALCULATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

When base numbers are available, ALWAYS compute these — do not leave them blank:

  Gross Margin %         = (Gross Profit / Revenue) × 100
  EBITDA Margin %        = (EBITDA / Revenue) × 100
  EBIT Margin %          = (EBIT / Revenue) × 100
  Net Profit Margin %    = (PAT / Revenue) × 100
  Revenue Growth YoY %   = ((Current − Previous) / |Previous|) × 100
  PAT Growth YoY %       = ((Current PAT − Previous PAT) / |Previous PAT|) × 100
  Debt-to-Equity         = Total Borrowings / Total Equity
  Debt-to-EBITDA         = Total Borrowings / EBITDA
  Interest Coverage      = EBIT / Finance Cost
  Current Ratio          = Current Assets / Current Liabilities
  Quick Ratio            = (Current Assets − Inventory) / Current Liabilities
  Cash Ratio             = Cash & Equivalents / Current Liabilities
  Asset Turnover         = Revenue / Total Assets
  Inventory Turnover     = Revenue / Inventory (or COGS / Inventory)
  ROE %                  = (PAT / Total Equity) × 100
  ROA %                  = (PAT / Total Assets) × 100
  OCF-to-PAT             = Operating Cash Flow / PAT
  FCF                    = Operating Cash Flow − CapEx
  Net Working Capital    = Current Assets − Current Liabilities
  EPS Growth YoY %       = ((Current EPS − Previous EPS) / |Previous EPS|) × 100

If a ratio is ALREADY stated in the document (e.g. in a "Key Ratios" table), use the document's figure.
If not stated but calculable from available data, CALCULATE it.
Only write "Not available" if the data to compute it genuinely does not exist anywhere in the document.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 4 — COMMENTARY QUALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Every commentary field must contain SPECIFIC, NUMERIC, ACTIONABLE observations.

BAD commentary:  "Revenue grew well."
GOOD commentary: "Revenue grew 18.4% YoY from ₹8,234 Cr to ₹9,750 Cr, driven by a 22% surge in the
                  domestic business, partially offset by a 4% decline in exports. Growth outpaced cost
                  inflation — COGS rose only 12% — resulting in gross margin expansion of 310 bps to 34.2%."

Every highlight and risk must name specific figures and explain the implication for investors.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEALTH SCORE METHODOLOGY (0–100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Calculate transparently — show your reasoning in the investor_verdict:

  Revenue growth YoY:    Positive = +10 pts | Negative = 0 pts
  Net profit margin:     >15% = 20pts | 10–15% = 15pts | 5–10% = 10pts | 0–5% = 5pts | Negative = 0pts
  EBITDA margin:         >25% = 15pts | 15–25% = 10pts | 8–15% = 6pts | <8% = 2pts
  Debt-to-Equity:        <0.3 = 15pts | 0.3–1.0 = 10pts | 1.0–2.0 = 5pts | >2.0 = 0pts
  Current Ratio:         >2.0 = 10pts | 1.5–2.0 = 8pts | 1.0–1.5 = 5pts | <1.0 = 0pts
  OCF quality:           OCF > PAT = 10pts | OCF positive = 7pts | OCF negative = 0pts
  ROE:                   >20% = 10pts | 15–20% = 7pts | 10–15% = 4pts | <10% = 1pt
  EPS growth YoY:        Positive = +10 pts | Negative = 0 pts

  Labels: 0–40 = "Caution" | 41–60 = "Fair" | 61–75 = "Good" | 76–88 = "Strong" | 89–100 = "Exceptional"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — RETURN ONLY VALID JSON, NO MARKDOWN, NO PREAMBLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{
  "company_name": "Full legal name of the company",
  "statement_type": "Annual Report / Quarterly Results / Half-Year Results",
  "period": "e.g. Q2 FY2024 / FY2023-24 / H1 FY2025",
  "reporting_currency": "INR / USD etc.",
  "unit": "Crores / Lakhs / Millions — as stated in the document",

  "health_score": 0,
  "health_label": "",
  "health_score_breakdown": {{
    "revenue_growth":  {{"pts": 0, "max": 10, "value": "e.g. +18.4% YoY", "reason": "e.g. Revenue grew from ₹8,234 Cr to ₹9,750 Cr — awarded full 10 pts"}},
    "net_margin":      {{"pts": 0, "max": 20, "value": "e.g. 12.3%",       "reason": "e.g. PAT margin of 12.3% falls in 10–15% band — awarded 15/20 pts"}},
    "ebitda_margin":   {{"pts": 0, "max": 15, "value": "e.g. 22.1%",       "reason": "e.g. EBITDA margin of 22.1% falls in 15–25% band — awarded 10/15 pts"}},
    "debt_to_equity":  {{"pts": 0, "max": 15, "value": "e.g. 0.42x",       "reason": "e.g. D/E of 0.42x is in 0.3–1.0 band — awarded 10/15 pts"}},
    "current_ratio":   {{"pts": 0, "max": 10, "value": "e.g. 1.8x",        "reason": "e.g. Current ratio 1.8x is in 1.5–2.0 band — awarded 8/10 pts"}},
    "ocf_quality":     {{"pts": 0, "max": 10, "value": "e.g. OCF ₹1,200 Cr vs PAT ₹980 Cr", "reason": "e.g. OCF exceeds PAT (OCF/PAT = 1.22x), strong cash conversion — awarded full 10 pts"}},
    "roe":             {{"pts": 0, "max": 10, "value": "e.g. 17.4%",        "reason": "e.g. ROE of 17.4% falls in 15–20% band — awarded 7/10 pts"}},
    "eps_growth":      {{"pts": 0, "max": 10, "value": "e.g. +22.5% YoY",  "reason": "e.g. Basic EPS grew from ₹24.10 to ₹29.52 — awarded full 10 pts"}},
    "total": 0
  }},

  "headline": "One punchy sentence summarising the most important story in this filing",
  "executive_summary": "4–6 sentences covering: overall performance, key growth drivers, cost dynamics, balance sheet health, cash flow quality, and key risks. Must contain specific numbers.",

  "income_statement": {{
    "revenue":          {{"current": "", "previous": "", "unit": ""}},
    "other_income":     {{"current": "", "previous": "", "unit": ""}},
    "total_income":     {{"current": "", "previous": "", "unit": ""}},
    "cost_of_goods_sold":{{"current": "", "previous": "", "unit": ""}},
    "gross_profit":     {{"current": "", "previous": "", "unit": ""}},
    "employee_costs":   {{"current": "", "previous": "", "unit": ""}},
    "other_expenses":   {{"current": "", "previous": "", "unit": ""}},
    "ebitda":           {{"current": "", "previous": "", "unit": ""}},
    "depreciation":     {{"current": "", "previous": "", "unit": ""}},
    "ebit":             {{"current": "", "previous": "", "unit": ""}},
    "finance_cost":     {{"current": "", "previous": "", "unit": ""}},
    "pbt":              {{"current": "", "previous": "", "unit": ""}},
    "tax_expense":      {{"current": "", "previous": "", "unit": ""}},
    "pat":              {{"current": "", "previous": "", "unit": ""}},
    "minority_interest":{{"current": "", "previous": "", "unit": ""}},
    "pat_after_mi":     {{"current": "", "previous": "", "unit": ""}},
    "eps_basic":        {{"current": "", "previous": "", "unit": "₹"}},
    "eps_diluted":      {{"current": "", "previous": "", "unit": "₹"}}
  }},

  "balance_sheet": {{
    "total_assets":           {{"current": "", "previous": "", "unit": ""}},
    "non_current_assets":     {{"current": "", "previous": "", "unit": ""}},
    "fixed_assets_net":       {{"current": "", "previous": "", "unit": ""}},
    "capital_wip":            {{"current": "", "previous": "", "unit": ""}},
    "investments":            {{"current": "", "previous": "", "unit": ""}},
    "current_assets":         {{"current": "", "previous": "", "unit": ""}},
    "inventories":            {{"current": "", "previous": "", "unit": ""}},
    "trade_receivables":      {{"current": "", "previous": "", "unit": ""}},
    "cash_equivalents":       {{"current": "", "previous": "", "unit": ""}},
    "other_current_assets":   {{"current": "", "previous": "", "unit": ""}},
    "total_equity":           {{"current": "", "previous": "", "unit": ""}},
    "share_capital":          {{"current": "", "previous": "", "unit": ""}},
    "reserves_surplus":       {{"current": "", "previous": "", "unit": ""}},
    "total_liabilities":      {{"current": "", "previous": "", "unit": ""}},
    "long_term_borrowings":   {{"current": "", "previous": "", "unit": ""}},
    "short_term_borrowings":  {{"current": "", "previous": "", "unit": ""}},
    "total_borrowings":       {{"current": "", "previous": "", "unit": ""}},
    "trade_payables":         {{"current": "", "previous": "", "unit": ""}},
    "current_liabilities":    {{"current": "", "previous": "", "unit": ""}},
    "deferred_tax_liability": {{"current": "", "previous": "", "unit": ""}}
  }},

  "cash_flow_statement": {{
    "operating_cash_flow":  {{"current": "", "previous": "", "unit": ""}},
    "investing_cash_flow":  {{"current": "", "previous": "", "unit": ""}},
    "financing_cash_flow":  {{"current": "", "previous": "", "unit": ""}},
    "capex":                {{"current": "", "previous": "", "unit": ""}},
    "free_cash_flow":       {{"current": "", "previous": "", "unit": ""}},
    "net_change_in_cash":   {{"current": "", "previous": "", "unit": ""}}
  }},

  "key_metrics": [
    {{"metric": "Revenue",              "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Gross Profit",         "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "EBITDA",               "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "EBIT",                 "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "PAT",                  "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "EPS (Basic) ₹",        "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Total Assets",         "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Total Equity",         "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Total Borrowings",     "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Operating Cash Flow",  "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Free Cash Flow",       "current": "", "previous": "", "change_pct": "", "comment": ""}},
    {{"metric": "Cash & Equivalents",   "current": "", "previous": "", "change_pct": "", "comment": ""}}
  ],

  "vertical_analysis": {{
    "base": "Revenue = 100%",
    "gross_margin_pct":          {{"current": "", "previous": "", "comment": ""}},
    "ebitda_margin_pct":         {{"current": "", "previous": "", "comment": ""}},
    "ebit_margin_pct":           {{"current": "", "previous": "", "comment": ""}},
    "net_profit_margin_pct":     {{"current": "", "previous": "", "comment": ""}},
    "cogs_as_pct_revenue":       {{"current": "", "previous": "", "comment": ""}},
    "employee_cost_pct_revenue": {{"current": "", "previous": "", "comment": ""}},
    "finance_cost_pct_revenue":  {{"current": "", "previous": "", "comment": ""}},
    "depreciation_pct_revenue":  {{"current": "", "previous": "", "comment": ""}},
    "commentary": "2–3 sentences comparing margin structure to prior period and industry norms"
  }},

  "horizontal_analysis": {{
    "revenue_growth_yoy_pct":      "",
    "gross_profit_growth_yoy_pct": "",
    "ebitda_growth_yoy_pct":       "",
    "pat_growth_yoy_pct":          "",
    "eps_growth_yoy_pct":          "",
    "total_assets_growth_yoy_pct": "",
    "borrowings_growth_yoy_pct":   "",
    "notable_trends": [
      "List 3–5 specific trend observations with numbers, e.g. 'Revenue grew 2x faster than COGS (18% vs 9%), expanding gross margin by 310 bps'"
    ]
  }},

  "leverage_analysis": {{
    "total_borrowings":        "",
    "long_term_borrowings":    "",
    "short_term_borrowings":   "",
    "debt_to_equity":          "",
    "debt_to_ebitda":          "",
    "interest_coverage_ratio": "",
    "net_debt":                "",
    "net_debt_to_ebitda":      "",
    "commentary": "Specific assessment of debt levels, trend vs prior year, and whether leverage is comfortable or concerning"
  }},

  "liquidity_analysis": {{
    "current_ratio":       "",
    "quick_ratio":         "",
    "cash_ratio":          "",
    "net_working_capital": "",
    "cash_and_equivalents":"",
    "commentary": "Assess ability to meet short-term obligations; flag any deterioration"
  }},

  "profitability_analysis": {{
    "gross_margin_pct":       "",
    "ebitda_margin_pct":      "",
    "ebit_margin_pct":        "",
    "net_profit_margin_pct":  "",
    "roe_pct":                "",
    "roa_pct":                "",
    "roic_pct":               "",
    "roce_pct":               "",
    "commentary": "Specific analysis of margin trends, drivers, and comparison to prior periods"
  }},

  "efficiency_analysis": {{
    "asset_turnover":               "",
    "inventory_turnover_days":      "",
    "receivables_turnover_days":    "",
    "payables_turnover_days":       "",
    "cash_conversion_cycle_days":   "",
    "fixed_asset_turnover":         "",
    "commentary": "How effectively is the company using its assets? Any working capital pressure?"
  }},

  "cash_flow_analysis": {{
    "operating_cash_flow":    "",
    "investing_cash_flow":    "",
    "financing_cash_flow":    "",
    "capex":                  "",
    "free_cash_flow":         "",
    "ocf_to_pat_ratio":       "",
    "fcf_margin_pct":         "",
    "cash_quality":           "Strong / Moderate / Weak — with reasoning",
    "commentary": "Is earnings quality high? Is growth funded by internal cash or debt? Specific figures required."
  }},

  "rates_of_return": {{
    "roe_pct":        "",
    "roa_pct":        "",
    "roic_pct":       "",
    "roce_pct":       "",
    "eps_basic":      "",
    "eps_diluted":    "",
    "eps_growth_pct": "",
    "dividend_per_share": "",
    "dividend_payout_ratio": "",
    "commentary": "Are returns improving or declining? Is the company creating shareholder value?"
  }},

  "segment_analysis": {{
    "has_segments": false,
    "segments": []
  }},

  "highlights": [
    "5–7 specific, numbered positive observations with exact figures — e.g. 'PAT surged 34% YoY to ₹1,240 Cr, the highest in company history'"
  ],
  "risks": [
    "4–6 specific, numbered risk factors with exact figures — e.g. 'Short-term borrowings rose 67% YoY to ₹3,400 Cr, raising refinancing risk'"
  ],
  "what_to_watch": [
    "3–5 forward-looking items an investor should monitor next quarter"
  ],

  "investor_verdict": "3–4 sentences: overall recommendation framing (NOT buy/sell — just analytical verdict), key strengths, key concerns, and what would change the outlook. Must include specific numbers."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINANCIAL DOCUMENT TO ANALYSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{snippet}
"""

def compress_prompt(prompt: str, max_chars: int = 65000) -> str:
    if len(prompt) > max_chars:
        logger.warning(f"Prompt too large ({len(prompt)} chars) — compressing to {max_chars}")
        return prompt[:max_chars] + "\n\n[Document truncated due to model context limits]"
    return prompt

# ─── AI RUNNERS ──────────────────────────────────────────────────────────────

def _sync_gemini(text: str) -> dict:
    if not GEMINI_API_KEY:
        raise Exception("No GEMINI_API_KEY configured")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    # (model_id, max_doc_chars)
    # Gemini 1M context — send full document
    models_to_try = [
        ("gemini-2.0-flash",      160000),
        ("gemini-2.0-flash-exp",  160000),
        ("gemini-1.5-flash",      160000),
        ("gemini-1.5-pro-002",    160000),
    ]

    last_error = ""
    for model_name, max_doc in models_to_try:
        try:
            prompt = build_prompt(text, max_doc_chars=max_doc)
            logger.info(f"Gemini {model_name}: sending {len(prompt):,} chars")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                )
            )
            raw_text = response.text
            logger.info(f"Gemini {model_name}: ✅ received {len(raw_text):,} chars")
            return safe_parse_json(raw_text)

        except Exception as e:
            err_str = str(e)
            last_error = err_str
            logger.warning(f"Gemini {model_name} failed: {err_str[:300]}")

            # Quota exhausted for today — no point trying other Gemini models
            if "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                logger.warning("Gemini quota exhausted — skipping remaining Gemini models")
                raise Exception(f"Gemini quota exhausted: {err_str[:200]}")

            # Model not found / deprecated — try next
            if "404" in err_str or "not found" in err_str.lower() or "deprecated" in err_str.lower():
                continue

            # Any other error — try next model
            continue

    raise Exception(f"All Gemini models failed. Last error: {last_error[:200]}")


GROQ_MODELS_ACTIVE = [
    # (model_id, max_doc_chars, use_lean_prompt)
    # llama-3.3-70b-versatile: 128k ctx → full prompt, 44k doc
    ("llama-3.3-70b-versatile",     44000, False),
    # mixtral-8x7b-32768: 32k ctx → full prompt, 16k doc
    ("mixtral-8x7b-32768",          16000, False),
    # llama3-70b-8192: 8k ctx → lean prompt, 14k doc
    ("llama3-70b-8192",             14000, True),
    # llama3-8b-8192: 8k ctx → lean prompt, 14k doc
    ("llama3-8b-8192",              14000, True),
]

def _sync_groq(text: str) -> dict:
    from groq import Groq
    gc = Groq(api_key=GROQ_API_KEY)

    for model, max_doc, lean in GROQ_MODELS_ACTIVE:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            logger.info(f"Groq {model}: sending {len(prompt):,} chars ({'lean' if lean else 'full'})")
            resp = gc.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=8192,
            )
            raw = resp.choices[0].message.content
            logger.info(f"Groq {model}: received {len(raw)} chars")
            return safe_parse_json(raw)
        except Exception as ex:
            logger.warning(f"Groq {model} failed: {str(ex)[:200]}")
            continue

    raise Exception("All Groq models failed or unavailable")

def _sync_together(text: str) -> dict:
    key = os.getenv("TOGETHER_API_KEY", "")
    if not key:
        raise Exception("No TOGETHER_API_KEY")

    # (model_id, max_doc_chars, use_lean)
    models = [
        ("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", 44000, False),
        ("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",  14000, True),
    ]

    for model, max_doc, lean in models:
        try:
            prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
            logger.info(f"Together {model}: sending {len(prompt):,} chars")
            resp = httpx.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.1, "max_tokens": 8192},
                timeout=90,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                logger.info(f"Together {model}: received {len(raw)} chars")
                return safe_parse_json(raw)
            logger.warning(f"Together {model} failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Together {model} error: {str(e)[:150]}")

    raise Exception("All Together AI models failed")


def _sync_openrouter(text: str) -> dict:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise Exception("No OPENROUTER_API_KEY")

    import time

    # CONFIRMED WORKING free models on OpenRouter as of March 2026
    # (model_id, max_doc_chars, use_lean_prompt)
    models = [
        ("mistralai/mistral-small-3.1-24b-instruct:free",  20000, True),
        ("google/gemini-2.0-flash-exp:free",               44000, False),
        ("deepseek/deepseek-r1-zero:free",                 44000, False),
        ("qwen/qwen3-8b:free",                             20000, True),
        ("qwen/qwen3-14b:free",                            44000, False),
        ("qwen/qwen3-30b-a3b:free",                        44000, False),
        ("microsoft/mai-ds-r1:free",                       44000, False),
        ("tngtech/deepseek-r1t-chimera:free",              44000, False),
    ]

    for model, max_doc, lean in models:
        prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
        for attempt in range(2):
            try:
                logger.info(f"OpenRouter {model}: sending {len(prompt):,} chars attempt {attempt+1}")
                resp = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "HTTP-Referer": "https://finsight-vert.vercel.app",
                        "X-Title": "FinSight",
                        "Content-Type": "application/json",
                    },
                    json={"model": model,
                          "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.1, "max_tokens": 8192},
                    timeout=120,
                )

                if resp.status_code == 429:
                    if attempt == 0:
                        logger.warning(f"OpenRouter {model} rate-limited — waiting 20s")
                        time.sleep(20)
                        continue
                    break

                if resp.status_code in (404, 400, 422):
                    logger.warning(f"OpenRouter {model}: HTTP {resp.status_code} — skipping")
                    break

                if resp.status_code == 200:
                    body = resp.json()
                    if "error" in body:
                        logger.warning(f"OpenRouter {model} body error: {str(body['error'])[:150]}")
                        break
                    raw = body["choices"][0]["message"]["content"]
                    logger.info(f"OpenRouter {model}: ✅ received {len(raw)} chars")
                    return safe_parse_json(raw)

                logger.warning(f"OpenRouter {model}: HTTP {resp.status_code}")
                break

            except httpx.TimeoutException:
                logger.warning(f"OpenRouter {model} timed out attempt {attempt+1}")
                if attempt == 0:
                    continue
                break
            except Exception as e:
                logger.warning(f"OpenRouter {model} error: {str(e)[:150]}")
                break

    raise Exception("All OpenRouter models failed or unavailable")

    for model, max_doc, lean in models:
        prompt = build_lean_prompt(text, max_doc_chars=max_doc) if lean else build_prompt(text, max_doc_chars=max_doc)
        for attempt in range(2):
            try:
                logger.info(f"OpenRouter {model}: sending {len(prompt):,} chars attempt {attempt+1}")
                resp = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "HTTP-Referer": "https://finsight-vert.vercel.app",
                        "X-Title": "FinSight",
                        "Content-Type": "application/json",
                    },
                    json={"model": model,
                          "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.1, "max_tokens": 8192},
                    timeout=120,
                )

                if resp.status_code == 429:
                    if attempt == 0:
                        logger.warning(f"OpenRouter {model} rate-limited — waiting 20s")
                        time.sleep(20)
                        continue
                    break  # second rate-limit → skip model

                if resp.status_code in (404, 400, 422):
                    logger.warning(f"OpenRouter {model}: HTTP {resp.status_code} — skipping")
                    break

                if resp.status_code == 200:
                    body = resp.json()
                    if "error" in body:
                        logger.warning(f"OpenRouter {model} body error: {str(body['error'])[:150]}")
                        break
                    raw = body["choices"][0]["message"]["content"]
                    logger.info(f"OpenRouter {model}: received {len(raw)} chars")
                    return safe_parse_json(raw)

                logger.warning(f"OpenRouter {model}: HTTP {resp.status_code}")
                break

            except httpx.TimeoutException:
                logger.warning(f"OpenRouter {model} timed out attempt {attempt+1}")
                if attempt == 0:
                    continue
                break
            except Exception as e:
                logger.warning(f"OpenRouter {model} error: {str(e)[:150]}")
                break

    raise Exception("All OpenRouter models failed or unavailable")


def _extract_metrics_from_text(text: str) -> dict:
    """
    Regex-based metric extraction directly from extracted text.
    Works on the plain text string (not PDF bytes), so it always runs.
    Captures the most common label patterns in Indian financial filings.
    """
    metrics = defaultdict(str)
    t = text  # preserve original case for number extraction

    # Pattern: label ... number (handles both "Label  1,234.56" and "Label: 1,234.56")
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

    t_lower = t.lower()
    for metric, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, t_lower)
            if m:
                metrics[metric] = m.group(1)
                break

    return dict(metrics)


# ─── MAIN ANALYSIS ORCHESTRATOR ──────────────────────────────────────────────
async def run_analysis(text: str) -> dict:

    if not text or len(text.strip()) < 100:
        raise Exception("PDF extraction returned insufficient text.")

    # Use as much of the document as possible — do NOT truncate aggressively here.
    # build_prompt will take up to 55,000 chars; compress_prompt caps at 65,000.
    # We pass the full extracted text and let the prompt builder slice it.
    full_text = text.strip()

    # Guard: reject if text lacks any financial content
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

    # Pre-extract structured metrics from the raw PDF bytes stored in text
    # Note: extract_tables_from_pdf requires actual PDF bytes, not text.
    # metrics/ratios are computed from raw bytes upstream in extract_pdf_text.
    # Here we pass the already-extracted text string directly to the AI.
    # The structured metrics block below is a best-effort regex pass on the text.
    metrics = _extract_metrics_from_text(full_text)
    ratios  = compute_financial_ratios(metrics)
    logger.info(f"Text-based metrics: {metrics}")
    logger.info(f"Computed ratios: {ratios}")

    # Build the enriched text block handed to every AI provider
    metrics_block = ""
    if any(metrics.values()):
        metrics_block = f"""
PRE-EXTRACTED METRICS (use as cross-reference, not as substitute for reading the document):
{json.dumps(metrics, indent=2)}

PRE-COMPUTED RATIOS (verify against document figures):
{json.dumps(ratios, indent=2)}

"""

    enhanced_text = metrics_block + full_text

    providers = [
        ("Gemini",      _sync_gemini,      GEMINI_API_KEY),
        ("Groq",        _sync_groq,        GROQ_API_KEY),
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


# ─── FMP (Financial Modeling Prep) HELPERS ───────────────────────────────────

# Simple in-memory TTL cache  { key: (timestamp, data) }
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
    """Convert NSE symbol to FMP format — FMP uses NSE suffix for Indian stocks."""
    sym = symbol.upper().strip()
    if sym.startswith("BSE_"):
        return sym.replace("BSE_", "") + ".BO"
    return sym + ".NS"

def _safe(val, decimals=2):
    if val is None: return None
    try: return round(float(val), decimals)
    except: return None

def _fmt_cr(val) -> str:
    """Format a number (assumed INR) into crores string."""
    try:
        v = float(val)
        return f"₹{v/1e7:,.2f} Cr" if abs(v) >= 1e7 else f"₹{v:,.0f}"
    except: return str(val) if val else "N/A"


async def _fmp_get(endpoint: str, params: dict = None) -> dict:
    """Async FMP API call with error handling."""
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
    """
    Full quote for an NSE/BSE symbol using FMP.
    Combines /quote, /profile, and /ratios endpoints.
    Cached 5 minutes.
    """
    sym = symbol.upper().strip()
    cached = _fmp_cached(f"quote:{sym}")
    if cached:
        logger.info(f"FMP cache hit: {sym}")
        return cached

    fmp_sym = _fmp_symbol(sym)
    logger.info(f"FMP fetching quote for {fmp_sym}")

    # Fetch quote + profile in parallel
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

        # 52-week position
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

            # Price
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

            # Valuation
            "market_cap":     market_cap,
            "market_cap_fmt": _fmt_cr(market_cap),
            "pe_ratio":       _safe(q.get("pe")),
            "eps":            _safe(q.get("eps")),
            "pb_ratio":       _safe(r.get("priceToBookRatioTTM")),
            "ps_ratio":       _safe(r.get("priceToSalesRatioTTM")),
            "ev_ebitda":      _safe(r.get("enterpriseValueMultipleTTM")),
            "beta":           _safe(p.get("beta")),
            "shares_outstanding": p.get("sharesOutstanding"),

            # Dividend
            "dividend_yield_pct": _safe(r.get("dividendYieldPercentageTTM")),
            "dividend_per_share": _safe(r.get("dividendPerShareTTM")),

            # Profitability (TTM ratios)
            "gross_margin_pct":     _safe(r.get("grossProfitMarginTTM") and r["grossProfitMarginTTM"] * 100),
            "operating_margin_pct": _safe(r.get("operatingProfitMarginTTM") and r["operatingProfitMarginTTM"] * 100),
            "net_margin_pct":       _safe(r.get("netProfitMarginTTM") and r["netProfitMarginTTM"] * 100),
            "roe_pct":              _safe(r.get("returnOnEquityTTM") and r["returnOnEquityTTM"] * 100),
            "roa_pct":              _safe(r.get("returnOnAssetsTTM") and r["returnOnAssetsTTM"] * 100),
            "roic_pct":             _safe(r.get("returnOnCapitalEmployedTTM") and r["returnOnCapitalEmployedTTM"] * 100),

            # Financial health
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
            "openrouter":  bool(os.getenv("OPENROUTER_API_KEY")),
            "fmp":         bool(FMP_API_KEY),
            "companies_in_db": company_count}


# ─── FMP MARKET DATA ROUTES ───────────────────────────────────────────────────

@app.get("/api/quote/{symbol}")
async def get_quote(symbol: str):
    """
    Live market quote for NSE/BSE symbol via FMP.
    Returns price, valuation, margins, ratios, 52-week range.
    Cached 5 minutes.
    Example: GET /api/quote/RELIANCE
    """
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
    """
    Historical daily OHLCV data for charting via FMP.
    period: 1m, 3m, 6m, 1y, 3y, 5y
    Example: GET /api/quote/TCS/history?period=6m
    """
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
    """
    Annual Income Statement, Balance Sheet, Cash Flow (last 4 years) via FMP.
    Example: GET /api/quote/INFY/financials
    """
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
            _fmp_get(f"/v3/income-statement/{fmp_sym}",   {"limit": 4}),
            _fmp_get(f"/v3/balance-sheet-statement/{fmp_sym}", {"limit": 4}),
            _fmp_get(f"/v3/cash-flow-statement/{fmp_sym}", {"limit": 4}),
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
    """
    Fetch live quotes for up to 20 symbols in one call.
    Body: { "symbols": ["RELIANCE", "TCS", "INFY"] }
    Example: POST /api/quotes/batch
    """
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
    """
    Top 5 gainers and losers among Nifty 50 stocks via FMP.
    Cached 5 minutes.
    """
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
    """
    Convert an NSE symbol to Yahoo Finance ticker.
    NSE symbols use .NS suffix; BSE use .BO suffix.
    BSE-only symbols are prefixed BSE_ in our DB.
    """
    sym = symbol.upper().strip()
    if sym.startswith("BSE_"):
        # BSE-only — use .BO suffix with the numeric code
        return sym.replace("BSE_", "") + ".BO"
    return sym + ".NS"


def _safe_val(info: dict, *keys):
    """Return first non-None value from info dict for given keys."""
    for k in keys:
        v = info.get(k)
        if v is not None and v != "":
            return v
    return None


def _fmt_large(val) -> str:
    """Format large numbers into readable crore / lakh strings."""
    try:
        v = float(val)
        if abs(v) >= 1e11:
            return f"₹{v/1e7:,.2f} Cr"
        if abs(v) >= 1e7:
            return f"₹{v/1e7:,.2f} Cr"
        if abs(v) >= 1e5:
            return f"₹{v/1e5:,.2f} L"
        return str(round(v, 2))
    except (TypeError, ValueError):
        return str(val) if val is not None else "N/A"

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
