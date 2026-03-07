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
        if score >= 3:
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


def extract_financial_snippet(raw_bytes: bytes, max_chars: int = 40000) -> str:
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

def split_into_chunks(text, size=6000, overlap=600):

    chunks = []
    start = 0

    while start < len(text):

        chunk = text[start:start + size]

        chunks.append(chunk)

        start += size - overlap

    logger.info(f"Split document into {len(chunks)} chunks")

    return chunks

def build_prompt(text: str) -> str:

    snippet = text[:35000]

    logger.info(f"Prompt snippet: {len(snippet)} chars")

    financial_keywords = [
        "revenue",
        "profit",
        "income",
        "assets",
        "crore",
        "lakh",
        "eps",
        "ebitda"
    ]

    found_kw = [
        kw for kw in financial_keywords
        if kw.lower() in snippet.lower()
    ]

    if len(found_kw) < 2:
        logger.warning(
            f"Snippet may not contain financial data. "
            f"Found keywords: {found_kw}. "
            f"Preview: {snippet[:300]}"
        )

    return f"""
You are FinSight — an institutional-grade equity research analyst specialising in Indian listed companies.

Your job is to analyse financial statements and produce a comprehensive, investor-grade report covering ALL major types of financial analysis.

━━━━━━━━━━━━━━━━━━
CRITICAL RULES
━━━━━━━━━━━━━━━━━━

1. Use ONLY numbers that appear in the document.
2. NEVER fabricate or estimate data.
3. If a metric is not in the document, write: "Not available in this filing".
4. Scan the FULL document before declaring any data unavailable.
5. Copy numbers EXACTLY as they appear — preserve commas and decimals.

Example:
Document shows: 20,078.39
Write exactly:  20,078.39  (not 2007.8, not 20078, not 20.07)

━━━━━━━━━━━━━━━━━━
WHAT IS FINANCIAL ANALYSIS?
━━━━━━━━━━━━━━━━━━

Financial analysis examines a company's financial data to understand its health, performance, and potential
to improve decision-making. Ratios are preferred over individual numbers because they reveal relationships
between figures. Past data is used to make projections. Key stakeholders — investors, analysts, lenders,
auditors — all use financial analysis to assess whether a company is healthy, well-run, and fairly valued.

━━━━━━━━━━━━━━━━━━
EXTRACTION TARGETS
━━━━━━━━━━━━━━━━━━

Extract every available figure from these categories:

INCOME STATEMENT
  Revenue / Total Income / Income from Operations / Net Sales
  Gross Profit
  EBITDA / Operating Profit
  EBIT
  Finance Cost / Interest Expense
  Depreciation & Amortisation
  Profit Before Tax (PBT)
  Net Profit / Profit After Tax (PAT)
  Basic EPS / Diluted EPS

BALANCE SHEET
  Total Assets | Current Assets | Non-Current Assets
  Cash & Cash Equivalents
  Inventories | Trade Receivables
  Total Liabilities | Current Liabilities | Non-Current Liabilities
  Borrowings / Total Debt
  Total Equity / Net Worth / Shareholders' Equity
  Reserves & Surplus | Share Capital

CASH FLOW
  Operating Cash Flow (OCF)
  Investing Cash Flow
  Financing Cash Flow
  Free Cash Flow (FCF)
  Capital Expenditure (CapEx)

━━━━━━━━━━━━━━━━━━
ANALYSIS FRAMEWORK — APPLY ALL 8 TYPES
━━━━━━━━━━━━━━━━━━

1. VERTICAL ANALYSIS
   Express each P&L line as % of Revenue; Balance Sheet lines as % of Total Assets.
   Compare against industry norms where possible.
   Flag if any cost exceeds typical benchmarks (e.g. COGS > 60% of revenue).

2. HORIZONTAL ANALYSIS (Trend Analysis)
   Calculate YoY and multi-period % changes for Revenue, Net Profit, EBITDA, Total Assets.
   Identify: Revenue growing faster/slower than costs, AR growing faster than sales,
   inventory outpacing sales, unusual spikes or drops.

3. LEVERAGE ANALYSIS
   Debt-to-Equity Ratio = Total Debt / Total Equity
   Debt-to-EBITDA Ratio = Total Debt / EBITDA
   Interest Coverage Ratio (EBIT / Finance Cost)
   Flag if D/E > 2.0 or interest coverage < 2.0x as risk signals.

4. LIQUIDITY ANALYSIS
   Current Ratio = Current Assets / Current Liabilities  (healthy: >1.5)
   Quick Ratio   = (Current Assets - Inventory) / Current Liabilities  (healthy: >1.0)
   Cash Ratio    = Cash / Current Liabilities
   Interpret the company's ability to meet short-term obligations.

5. PROFITABILITY ANALYSIS
   Gross Margin     = Gross Profit / Revenue
   EBITDA Margin    = EBITDA / Revenue
   EBIT Margin      = EBIT / Revenue
   Net Profit Margin = Net Profit / Revenue
   Return on Equity (ROE) = Net Profit / Total Equity
   Return on Assets (ROA) = Net Profit / Total Assets

6. EFFICIENCY ANALYSIS
   Asset Turnover    = Revenue / Total Assets
   Inventory Turnover = Revenue / Inventory
   OCF-to-Current-Liabilities = OCF / Current Liabilities
   Assess how effectively the company converts assets into revenue.

7. CASH FLOW ANALYSIS
   Is Operating Cash Flow positive and growing?
   FCF = OCF - CapEx. Is FCF sufficient to fund dividends and growth?
   Is the company funding operations through debt or its own cash flows?
   Cash quality: Is PAT backed by strong OCF (OCF/PAT ratio)?

8. RATES OF RETURN & VALUATION SIGNALS
   ROE, ROA, ROIC (if data allows).
   EPS trend (Basic and Diluted). Is EPS growing?
   Note if valuation multiples (P/E, P/B) are mentioned.

━━━━━━━━━━━━━━━━━━
HEALTH SCORE CRITERIA
━━━━━━━━━━━━━━━━━━

Score the company 0–100 based on:
- Revenue growth trend (+10 points if growing YoY)
- Net profit margin (>10% = 15pts, 5–10% = 10pts, 0–5% = 5pts, negative = 0pts)
- EBITDA margin (>20% = 15pts, 10–20% = 10pts, <10% = 5pts)
- Debt-to-Equity (0–0.5 = 15pts, 0.5–1.5 = 10pts, 1.5–2.5 = 5pts, >2.5 = 0pts)
- Current Ratio (>2 = 10pts, 1–2 = 7pts, <1 = 0pts)
- OCF positive = 10pts
- ROE >15% = 10pts, 10–15% = 7pts, <10% = 3pts
- EPS growth = 5pts

Labels: 0–40 = "Caution", 41–60 = "Fair", 61–75 = "Good", 76–90 = "Strong", 91–100 = "Exceptional"

━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — RETURN ONLY VALID JSON
━━━━━━━━━━━━━━━━━━

{{
  "company_name": "",
  "statement_type": "",
  "period": "",

  "health_score": 0,
  "health_label": "",

  "headline": "",
  "executive_summary": "",

  "key_metrics": [
    {{"metric": "Revenue",            "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "Gross Profit",       "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "EBITDA",             "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "EBIT",               "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "Net Profit (PAT)",   "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "EPS (Basic)",        "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "Total Assets",       "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "Total Equity",       "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "Total Debt",         "current": "", "previous": "", "change": "", "comment": ""}},
    {{"metric": "Operating Cash Flow","current": "", "previous": "", "change": "", "comment": ""}}
  ],

  "vertical_analysis": {{
    "gross_margin_pct": "",
    "ebitda_margin_pct": "",
    "ebit_margin_pct": "",
    "net_profit_margin_pct": "",
    "cost_of_revenue_pct": "",
    "finance_cost_pct_revenue": "",
    "commentary": ""
  }},

  "horizontal_analysis": {{
    "revenue_growth_yoy": "",
    "net_profit_growth_yoy": "",
    "ebitda_growth_yoy": "",
    "total_assets_growth_yoy": "",
    "notable_trends": []
  }},

  "leverage_analysis": {{
    "debt_to_equity": "",
    "debt_to_ebitda": "",
    "interest_coverage_ratio": "",
    "total_debt": "",
    "commentary": ""
  }},

  "liquidity_analysis": {{
    "current_ratio": "",
    "quick_ratio": "",
    "cash_ratio": "",
    "net_working_capital": "",
    "commentary": ""
  }},

  "profitability_analysis": {{
    "gross_margin": "",
    "ebitda_margin": "",
    "net_profit_margin": "",
    "roe": "",
    "roa": "",
    "commentary": ""
  }},

  "efficiency_analysis": {{
    "asset_turnover": "",
    "inventory_turnover": "",
    "ocf_to_current_liabilities": "",
    "commentary": ""
  }},

  "cash_flow_analysis": {{
    "operating_cash_flow": "",
    "free_cash_flow": "",
    "capex": "",
    "ocf_to_pat_ratio": "",
    "cash_quality": "",
    "commentary": ""
  }},

  "rates_of_return": {{
    "roe": "",
    "roa": "",
    "roic": "",
    "eps_basic": "",
    "eps_diluted": "",
    "eps_growth_yoy": "",
    "commentary": ""
  }},

  "highlights": [],
  "risks": [],
  "what_to_watch": [],

  "investor_verdict": ""
}}

━━━━━━━━━━━━━━━━━━
FINANCIAL DOCUMENT
━━━━━━━━━━━━━━━━━━

{snippet}
"""

def compress_prompt(prompt: str, max_chars: int = 40000) -> str:
    if len(prompt) > max_chars:
        logger.warning(f"Prompt too large ({len(prompt)} chars) — compressing to {max_chars}")
        return prompt[:max_chars] + "\n\n[Document truncated due to size limits]"
    return prompt

# ─── AI RUNNERS ──────────────────────────────────────────────────────────────

def _sync_gemini(text: str) -> dict:
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        models_to_try = [
            "gemini-2.0-flash-exp",
            "gemini-1.5-flash",
            "gemini-1.5-pro-002"
        ]

        for model_name in models_to_try:
            try:
                prompt = compress_prompt(build_prompt(text))

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=8192,
                    )
                )

                raw_text = response.text
                logger.info(f"Gemini {model_name}: {len(raw_text)} chars")
                return safe_parse_json(raw_text)

            except Exception as e:
                err_str = str(e)
                logger.warning(f"Gemini {model_name} failed: {err_str[:150]}")
                if "429" in err_str or "quota" in err_str.lower():
                    continue
                if "404" in err_str or "not found" in err_str.lower():
                    continue

        raise Exception("All Gemini models failed")

    except ImportError:
        logger.warning("New google-genai package not found, using old API")

        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)

        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        resp = model.generate_content(build_prompt(text))

        return safe_parse_json(resp.text)


GROQ_MODELS_ACTIVE = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "deepseek-r1-distill-llama-70b",
]

def _sync_groq(text: str) -> dict:
    from groq import Groq

    gc = Groq(api_key=GROQ_API_KEY)

    prompt = compress_prompt(build_prompt(text))

    for model in GROQ_MODELS_ACTIVE:
        try:
            resp = gc.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=8192
            )

            raw = resp.choices[0].message.content
            logger.info(f"Groq {model}: {len(raw)} chars")
            return safe_parse_json(raw)

        except Exception as ex:
            err_str = str(ex)
            logger.warning(f"Groq {model} failed: {err_str[:150]}")

            if "429" in err_str or "rate limit" in err_str.lower():
                continue
            if "400" in err_str or "decommissioned" in err_str.lower():
                continue
            if "413" in err_str or "too large" in err_str.lower():
                continue

    raise Exception("All Groq models failed or unavailable")    

def _sync_together(text: str) -> dict:
    key = os.getenv("TOGETHER_API_KEY", "")
    if not key:
        raise Exception("No TOGETHER_API_KEY")

    models = [
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    ]

    prompt = compress_prompt(build_prompt(text))

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
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 8192
                },
                timeout=90
            )

            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                logger.info(f"Together {model}: {len(raw)} chars")
                return safe_parse_json(raw)
            else:
                logger.warning(f"Together {model} failed: {resp.status_code}")

        except Exception as e:
            logger.warning(f"Together {model} error: {str(e)[:150]}")

    raise Exception("All Together AI models failed")


def _sync_openrouter(text: str) -> dict:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise Exception("No OPENROUTER_API_KEY")

    import time

    models = [
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "qwen/qwen-2.5-7b-instruct:free",
    ]

    prompt = compress_prompt(build_prompt(text))

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
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
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
                    logger.info(f"OpenRouter {model}: {len(raw)} chars")
                    return safe_parse_json(raw)

                else:
                    logger.warning(f"OpenRouter {model}: HTTP {resp.status_code}")
                    break

            except Exception as e:
                logger.warning(f"OpenRouter {model} error: {str(e)[:150]}")
                break

    raise Exception("All OpenRouter models failed")


# ─── MAIN ANALYSIS ORCHESTRATOR ──────────────────────────────────────────────
async def run_analysis(text: str) -> dict:

    if not text or len(text.strip()) < 100:
        raise Exception("PDF extraction returned insufficient text.")

    # Split large documents
    chunks = split_into_chunks(text)

    # Use first few chunks to guide analysis
    text = "\n\n".join(chunks[:4])

    # Guard: reject if text is too short or lacks any financial content
    if not text or len(text.strip()) < 100:
        raise Exception("PDF extraction returned insufficient text. The file may be scanned, empty, or corrupted.")

    financial_keywords = ["revenue", "profit", "income", "assets", "crore", "lakh", "eps", "ebitda", "loss"]
    found_kw = [kw for kw in financial_keywords if kw.lower() in text.lower()]
    if len(found_kw) < 2:
        raise Exception(
            f"Extracted text does not appear to contain financial data "
            f"(found only: {found_kw}). "
            f"Please verify the PDF is a financial results document. "
            f"Text preview: {text[:200]}"
        )

    logger.info(f"Analysis starting — text: {len(text)} chars, keywords found: {found_kw}")

    loop = asyncio.get_event_loop()
    errors = []

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
            logger.info(f"Trying {provider_name}...")
            tables = extract_tables_from_pdf(text.encode())
            metrics = parse_financial_metrics(tables)
            ratios  = compute_financial_ratios(metrics)

            logger.info(f"Structured metrics extracted: {metrics}")
            logger.info(f"Computed ratios: {ratios}")

            enhanced_text = f"""
Extracted financial metrics:

{json.dumps(metrics, indent=2)}

Computed financial ratios (cross-check your calculations against these):

{json.dumps(ratios, indent=2)}

Financial document:

{text}
"""
            result = await loop.run_in_executor(executor, func, enhanced_text)
            logger.info(f"{provider_name} succeeded!")
            return result
        except Exception as e:
            error_msg = str(e)[:200]
            logger.warning(f"{provider_name} failed: {error_msg}")
            errors.append(f"{provider_name}: {error_msg}")

    error_summary = " | ".join(errors) if errors else "No API keys configured"
    raise Exception(f"All AI providers failed. {error_summary}")


# ─── ROUTES ──────────────────────────────────────────────────────────────────
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
