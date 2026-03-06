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
def build_prompt(text: str) -> str:
    snippet = text[:35000]
    logger.info(f"Prompt snippet: {len(snippet)} chars")

    # Sanity check — warn if snippet looks too short or lacks financial content
    financial_keywords = ["revenue", "profit", "income", "assets", "crore", "lakh", "eps", "ebitda"]
    found_kw = [kw for kw in financial_keywords if kw.lower() in snippet.lower()]
    if len(found_kw) < 2:
        logger.warning(f"Snippet may not contain financial data. Found keywords: {found_kw}. Preview: {snippet[:300]}")

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
CRITICAL DATA INTEGRITY RULES — READ FIRST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. USE ONLY NUMBERS EXPLICITLY PRESENT IN THE DOCUMENT.
   - Do NOT invent, estimate, or carry forward numbers not in the text.
   - If the document is a newspaper extract or partial filing, it will contain a [SYSTEM NOTE] saying so.
     In that case, mark any unavailable metric as "Not available in this filing extract".
   - NEVER fabricate Balance Sheet items (Debt, Current Ratio, Cash, Working Capital) from a quarterly extract.

B. NUMBER ACCURACY — CRITICAL:
   - Read numbers exactly as they appear. Do NOT drop digits or shift decimal places.
   - If you see "20,078.39" do NOT write "2,007.8" or "2007.8". Write "20,078.39".
   - If you see "3,066.03" do NOT write "306.03". Write "3,066.03".
   - Always check: does the number make sense vs other numbers in context?
     (e.g. Net Profit cannot be larger than Revenue)
   - Commas in Indian numbering: 1,00,000 = 100000 (one lakh), NOT 1000000.

C. STANDALONE vs CONSOLIDATED:
   - If both are present, use STANDALONE figures as primary (labelled clearly).
   - If only consolidated is present, use those and label as "Consolidated".
   - NEVER mix standalone and consolidated numbers in the same metric.

D. CALCULATIONS — DO THE MATH CORRECTLY:
   - Growth % = ((Current - Previous) / |Previous|) × 100
   - Net Margin = (Net Profit / Revenue) × 100
   - ROE = (Net Profit / Total Equity) × 100
   - Debt/Equity = Total Debt / Total Equity
   - Interest Coverage = EBIT / Finance Costs
   - Current Ratio = Current Assets / Current Liabilities

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXTRACTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. SEARCH THE ENTIRE DOCUMENT for each metric before saying "Not available"
2. Alternate names to look for:
   - Total Assets = "Total Assets" OR balance sheet total
   - Total Debt = "Total Borrowings" OR "Debt Securities" OR "Borrowings" OR "Loans"
   - Operating Cash Flow = "Cash from Operating Activities" OR "Net Cash from Operations"
   - Interest Coverage = calculate from "Finance Costs" and "EBIT" or "EBITDA"
3. For NBFCs: Total Debt = Debt Securities + Borrowings + Subordinated Liabilities
4. For Defense/PSU: Order book, government advances, and contract pipeline are critical context
5. Only write "Not available in this filing" if numbers are truly absent after thorough search

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
- 9-12  = Average (D/E 0.5-1.5, moderate leverage)
- 0-8   = Weak    (D/E >1.5, high debt burden)
- If Balance Sheet data is unavailable: score based on what IS available; note limitation.

LIQUIDITY (0-10):
- 9-10 = Strong   (Current Ratio >1.5, strong cash position)
- 6-8  = Average  (Current Ratio 1.0-1.5, adequate cash)
- 0-5  = Weak     (Current Ratio <1.0, cash concerns)
- If Liquidity data is unavailable: assign score of 5 and note "Insufficient data".

CASH FLOW (0-15):
- 13-15 = Strong  (OCF > Net Profit, consistent generation)
- 9-12  = Average (OCF approximately equals Net Profit, stable)
- 0-8   = Weak    (OCF < Net Profit or negative)
- If Cash Flow data is unavailable: assign score of 7 and note "Not reported in extract".

GOVERNANCE & RISK (0-15):
- 13-15 = Strong  (No red flags, AAA/AA+ rating, clean audit, low promoter pledge)
- 9-12  = Average (Minor concerns, good rating, no major flags)
- 0-8   = Weak    (Auditor qualifications, governance issues, high pledging)

INDUSTRY POSITION (0-10):
- 9-10 = Strong   (Market leader, durable moat, pricing power)
- 6-8  = Average  (At par with peers, no significant moat)
- 0-5  = Weak     (Below peer average, losing market share)

RATING MUST MATCH SCORE:
- Score >= 80% of max = "Strong" | 60-79% = "Average" | <60% = "Weak"
- Score 12/15 = "Average" (NOT "Weak"). Score 16/20 = "Strong" (NOT "Average").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON OUTPUT SCHEMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "company_name": "Full legal name exactly as it appears in the document",
  "statement_type": "Annual Report / Half-Year Results / Quarterly Results / Newspaper Extract",
  "period": "e.g. Q3 FY2025-26 (Quarter ended 31 December 2025)",
  "currency": "INR Lakhs / INR Crores / USD Millions",
  "data_source": "Standalone / Consolidated / Mixed (specify which metrics are which)",
  "data_completeness": "Full Filing / Partial Extract / Newspaper Advertisement",
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
        "rating": "Strong / Average / Weak",
        "reasoning": "State actual ROE %, Net Margin %, and trend. Explain WHY this score."
      }},
      {{
        "category": "Growth",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "Revenue grew X% (explain volume vs price), Profit grew Y%. Explain gap."
      }},
      {{
        "category": "Balance Sheet",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "D/E ratio X, Total Debt Y. If unavailable say so and explain scoring basis."
      }},
      {{
        "category": "Liquidity",
        "weight": 10,
        "score": 0,
        "max": 10,
        "rating": "Strong / Average / Weak",
        "reasoning": "Current Ratio X, Cash Y. If unavailable, state 'Insufficient data in filing'."
      }},
      {{
        "category": "Cash Flow",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "OCF X vs PAT Y. If unavailable in extract, state so explicitly."
      }},
      {{
        "category": "Governance & Risk",
        "weight": 15,
        "score": 0,
        "max": 15,
        "rating": "Strong / Average / Weak",
        "reasoning": "Credit rating, auditor stance, promoter pledge, any red flags found."
      }},
      {{
        "category": "Industry Position",
        "weight": 10,
        "score": 0,
        "max": 10,
        "rating": "Strong / Average / Weak",
        "reasoning": "Market rank vs named peers, moat source, competitive advantage."
      }}
    ]
  }},

  "executive_summary": "5-6 sentences. Open with the company name and period. Use REAL numbers from the document. Explain what drove performance, key risk, and what investors must watch. Do NOT use placeholder language.",

  "headline": "One punchy, memorable sentence max 15 words capturing the essence of this result.",

  "investment_label": "Strong Buy / Buy / Hold / Reduce / Avoid",

  "investor_verdict": "3-4 sentences. Direct recommendation with specific reasoning using actual numbers. State what would change the view. Write as senior analyst to institutional client.",

  "for_long_term_investors": "2-3 sentences on compounding potential, moat durability, and risk of permanent capital loss.",

  "for_short_term_traders": "2-3 sentences on near-term catalysts and key triggers for next quarter.",

  "bottom_line": "One single memorable sentence — the most important thing any investor must know right now.",

  "explain_like_15": "5 lines using small shop analogy. No jargon. A 15-year-old must understand how the business is doing and why.",

  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "ACTUAL number from document", "previous": "ACTUAL number", "change": "CALCULATED %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "What drove this? Volume or price?"}},
    {{"label": "Net Profit / PAT", "current": "ACTUAL number", "previous": "ACTUAL number", "change": "CALCULATED %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Growing faster or slower than revenue? Why?"}},
    {{"label": "EBITDA", "current": "Calculate or extract", "previous": "ACTUAL", "change": "CALCULATED %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Operating leverage story"}},
    {{"label": "EBITDA Margin", "current": "Calculate %", "previous": "ACTUAL %", "change": "bps change", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Expanding or compressing? Key cost driver?"}},
    {{"label": "Net Profit Margin", "current": "Calculate %", "previous": "ACTUAL %", "change": "bps change", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Divergence from EBITDA margin signals tax/interest dynamics"}},
    {{"label": "EPS (Basic)", "current": "ACTUAL", "previous": "ACTUAL", "change": "CALCULATED %", "trend": "up/down/neutral", "signal": "Strong/Good/Average/Weak", "comment": "Per-share value creation"}},
    {{"label": "Total Assets", "current": "Extract or Not available in this filing", "previous": "ACTUAL or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Asset growth vs revenue growth efficiency"}},
    {{"label": "Total Debt", "current": "Extract Borrowings + Debt Securities or Not available", "previous": "ACTUAL or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Debt trajectory and purpose"}},
    {{"label": "Cash & Equivalents", "current": "ACTUAL or Not available", "previous": "ACTUAL or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Cash burn or accumulation"}},
    {{"label": "ROE", "current": "Calculate PAT/Equity or Not available", "previous": "ACTUAL or N/A", "change": "bps or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Equity deployment effectiveness"}},
    {{"label": "ROCE", "current": "Calculate if possible or Not available", "previous": "ACTUAL or N/A", "change": "bps or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Capital allocation quality"}},
    {{"label": "Debt to Equity", "current": "CALCULATE or Not available", "previous": "ACTUAL or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Leverage level"}},
    {{"label": "Interest Coverage", "current": "CALCULATE EBIT/Finance Costs or Not available", "previous": "ACTUAL or N/A", "change": "x or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Debt servicing safety margin"}},
    {{"label": "Current Ratio", "current": "Calculate CA/CL or Not available", "previous": "ACTUAL or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Short-term financial health"}},
    {{"label": "Operating Cash Flow", "current": "EXTRACT from Cash Flow Statement or Not available in extract", "previous": "ACTUAL or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "OCF vs PAT — is profit real?"}},
    {{"label": "Free Cash Flow", "current": "OCF minus Capex or Not available", "previous": "Calculate or N/A", "change": "% or N/A", "trend": "up/down/neutral/unknown", "signal": "Strong/Good/Average/Weak/Unknown", "comment": "Cash after sustaining the business"}}
  ],

  "segment_analysis": {{
    "available": true,
    "segments": [
      {{
        "name": "Segment name",
        "revenue": "ACTUAL",
        "revenue_share": "% of total",
        "growth": "YoY %",
        "margin": "If available or N/A",
        "insight": "What is driving or dragging this segment?"
      }}
    ],
    "key_takeaway": "Which segment is the real value driver? Which is the hidden risk?"
  }},

  "cash_flow_deep_dive": {{
    "operating_cf": "ACTUAL or Not available in this filing",
    "investing_cf": "ACTUAL or Not available",
    "financing_cf": "ACTUAL or Not available",
    "free_cash_flow": "OCF - Capex or Not available",
    "capex": "ACTUAL if available or Not available",
    "cash_conversion_quality": "High / Medium / Low / Insufficient data",
    "ocf_vs_pat_insight": "Is profit backed by real cash? Explain gap with specific reasons. If data absent say so.",
    "red_flags": ["Specific FCF concern or N/A if data unavailable"]
  }},

  "balance_sheet_deep_dive": {{
    "asset_quality": "What are major assets? Productive? Any impairment risk? Or Not available.",
    "debt_profile": "Maturity, cost, secured vs unsecured — or Not available in this filing.",
    "working_capital_insight": "Receivables days, payable days — or Not available.",
    "hidden_strengths": ["Non-obvious strength or N/A"],
    "hidden_risks": ["Non-obvious risk or N/A"],
    "total_debt": "EXTRACT or Not available",
    "net_worth": "EXTRACT or Not available",
    "debt_to_equity": "CALCULATE or Not available",
    "interest_coverage": "CALCULATE or Not available",
    "debt_comfort_level": "Comfortable / Moderate / Stressed / Insufficient data"
  }},

  "growth_quality": {{
    "revenue_growth_context": "Organic or inorganic? Volume-led or price-led? Sustainable?",
    "profit_growth_context": "Faster or slower than revenue? What explains the divergence?",
    "margin_trend": "Expanding / Compressing / Stable — structural reason?",
    "growth_outlook": "Accelerating / Stable / Decelerating / Uncertain",
    "catalysts": ["Specific company-relevant catalyst 1", "Catalyst 2"],
    "headwinds": ["Specific headwind 1 with reasoning", "Headwind 2"]
  }},

  "industry_context": {{
    "sector_tailwinds": ["Tailwind 1 relevant to this company", "Tailwind 2"],
    "sector_headwinds": ["Headwind 1", "Headwind 2"],
    "competitive_position": "Where does this company sit vs named peers?",
    "peer_benchmarks": "Compare key margins vs named sector peers",
    "regulatory_environment": "Policy or regulatory dependency that impacts outlook"
  }},

  "red_flags": [
    {{
      "flag": "Specific non-generic flag title",
      "severity": "High / Medium / Low",
      "explanation": "What the concern is and why it matters",
      "what_to_watch": "Specific metric or event that confirms or dismisses this risk"
    }}
  ],

  "strengths_and_moats": [
    {{
      "strength": "Specific competitive strength",
      "why_it_matters": "Why this is a durable moat — not just a positive data point",
      "risk_to_moat": "What could erode this advantage?"
    }}
  ],

  "valuation_context": {{
    "note": "Valuation data not provided in document. Assessment based on financials only.",
    "book_value_per_share": "Calculate if share count available or Not available",
    "pb_ratio": "If market price available or Not available",
    "earnings_quality": "High / Medium / Low — and why",
    "analyst_comment": "Premium or discount to peers likely? Why?"
  }},

  "investor_faq": [
    {{
      "question": "Specific question a real investor would ask about THIS company",
      "answer": "Direct expert answer using actual numbers. 2-4 sentences."
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
      "question": "Fifth question focused on the biggest risk",
      "answer": "Direct expert answer"
    }}
  ],

  "key_monitorables": [
    {{
      "metric": "Specific metric to track",
      "why": "Why this is the most important forward indicator for this specific company",
      "trigger": "Specific threshold or event that signals a turn"
    }},
    {{
      "metric": "Second monitorable",
      "why": "Company-specific reasoning",
      "trigger": "Specific threshold"
    }},
    {{
      "metric": "Third monitorable",
      "why": "Specific reasoning",
      "trigger": "Specific trigger"
    }}
  ],

  "profitability": {{
    "analysis": "Detailed analysis with actual numbers and business model context",
    "gross_margin_current": "Calculate or extract % or N/A",
    "gross_margin_previous": "ACTUAL % or N/A",
    "net_margin_current": "CALCULATE PAT/Revenue — do not skip this",
    "net_margin_previous": "ACTUAL %",
    "ebitda_margin_current": "CALCULATE",
    "ebitda_margin_previous": "ACTUAL %",
    "roe": "CALCULATE PAT/Equity x 100 or Not available",
    "roa": "CALCULATE PAT/Assets x 100 or Not available",
    "key_cost_drivers": ["Actual cost item 1 with real numbers", "Cost driver 2 with trend"]
  }},

  "liquidity": {{
    "analysis": "Analysis with real numbers or note data unavailability",
    "current_ratio": "CALCULATE CA/CL or Not available",
    "quick_ratio": "Calculate if data available or N/A",
    "cash_position": "EXTRACT or Not available",
    "operating_cash_flow": "EXTRACT from Cash Flow Statement or Not available",
    "free_cash_flow": "OCF - Capex or Not available",
    "day_to_day_assessment": "Smooth / Adequate / Tight / Insufficient data"
  }},

  "highlights": [
    "Specific strength 1 with actual numbers",
    "Specific strength 2 with context",
    "Specific strength 3",
    "Specific strength 4",
    "Specific strength 5"
  ],

  "risks": [
    "Specific risk 1 tied to actual numbers — not generic",
    "Specific risk 2",
    "Specific risk 3",
    "Specific risk 4",
    "Specific risk 5"
  ],

  "what_to_watch": [
    "Specific watch item 1 for next reporting period",
    "Specific watch item 2",
    "Specific watch item 3"
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL REMINDERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Company name MUST be taken from the document — never invent it
- Numbers MUST be copied exactly — never drop digits or shift decimals
- If standalone and consolidated both appear, use standalone as primary
- Missing data = "Not available in this filing" — never fabricate it
- Rating MUST match score per calibration above
- investor_faq must be company-specific questions, not generic
- bottom_line must be one memorable, direct, quotable sentence
- headline must stand alone as a financial news headline

FINANCIAL DOCUMENT:
{snippet}"""

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
            result = await loop.run_in_executor(executor, func, text)
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
