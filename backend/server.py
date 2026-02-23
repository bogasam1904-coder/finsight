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

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MONGO_URL       = os.getenv("MONGO_URL", "mongodb://localhost:27017")
JWT_SECRET      = os.getenv("JWT_SECRET", "finsight-secret-key-2024")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 30
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")

executor = ThreadPoolExecutor(max_workers=4)
app = FastAPI(title="FinSight API v12")

# ── CORS ──────────────────────────────────────────────────────────────────────
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
mongo_client  = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db            = mongo_client.finsight
users_col     = db.users
analyses_col  = db.analyses
companies_col = db.companies   # ← dynamic company master (all NSE + BSE listings)

# ── AUTH ──────────────────────────────────────────────────────────────────────
pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def hash_pw(pw: str) -> str:   return pwd_ctx.hash(pw)
def verify_pw(p: str, h: str): return pwd_ctx.verify(p, h)

def create_token(uid: str) -> str:
    exp = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": uid, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        uid = payload.get("sub")
        if not uid:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Token expired or invalid — please sign in again")
    user = await users_col.find_one({"user_id": uid})
    if not user:
        raise HTTPException(401, "Account not found — please sign in again")
    return user

async def get_optional_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        return None
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        uid = payload.get("sub")
        if not uid:
            return None
        return await users_col.find_one({"user_id": uid})
    except Exception:
        return None

# ── MODELS ────────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AnalyzeFromURLRequest(BaseModel):
    pdf_url: str
    filename: str
    source: str  # "nse" | "bse"

# ── HTTP HEADERS ──────────────────────────────────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
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


# ═══════════════════════════════════════════════════════════════════════════════
#  DYNAMIC COMPANY MASTER  — fetches ALL listed companies from NSE + BSE
# ═══════════════════════════════════════════════════════════════════════════════

async def sync_nse_companies() -> int:
    """
    NSE publishes a full equity list as a CSV:
      https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
    Columns: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING,
             PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
    ~2,200+ rows covering every NSE-listed equity.
    """
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    count = 0
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            r = await client.get(url, headers=NSE_HEADERS)
            r.raise_for_status()

        lines = r.text.splitlines()
        if len(lines) < 2:
            logger.warning("NSE CSV returned too few lines")
            return 0

        header = [h.strip().upper() for h in lines[0].split(",")]
        try:
            sym_idx  = header.index("SYMBOL")
            name_idx = header.index("NAME OF COMPANY")
            isin_idx = header.index("ISIN NUMBER") if "ISIN NUMBER" in header else -1
        except ValueError as e:
            logger.error(f"NSE CSV header mismatch: {header} — {e}")
            return 0

        from pymongo import UpdateOne
        ops = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(sym_idx, name_idx):
                continue
            symbol = parts[sym_idx].strip().upper()
            name   = parts[name_idx].strip().title()
            isin   = parts[isin_idx].strip() if isin_idx != -1 and len(parts) > isin_idx else ""
            if not symbol or not name:
                continue
            ops.append(UpdateOne(
                {"symbol": symbol},
                {"$set": {
                    "symbol": symbol, "name": name, "isin": isin,
                    "nse_listed": True, "active": True,
                    "updated_at": datetime.utcnow().isoformat(),
                }},
                upsert=True,
            ))

        for i in range(0, len(ops), 500):
            await companies_col.bulk_write(ops[i:i+500])
            count += len(ops[i:i+500])

        logger.info(f"NSE sync complete: {count} records upserted")
    except Exception as e:
        logger.error(f"NSE company sync failed: {e}")
    return count


async def sync_bse_companies() -> int:
    """
    BSE provides a full scrip master via:
      https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active
    Returns JSON list with BSE code, NSE symbol, company name, ISIN, industry, etc.
    ~5,500+ active equities.
    """
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
        "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
    )
    count = 0
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(url, headers=BSE_HEADERS)
            r.raise_for_status()
            data = r.json()

        items = data if isinstance(data, list) else data.get("Table", data.get("data", []))
        logger.info(f"BSE returned {len(items)} scrips")

        from pymongo import UpdateOne
        ops = []
        for item in items:
            bse_code = str(
                item.get("SCRIP_CD") or item.get("scripCode") or item.get("ScripCode") or ""
            ).strip()
            nse_sym = (
                item.get("NSE_SYMBOL") or item.get("nseSymbol") or item.get("scrip_id") or ""
            ).strip().upper()
            name = (
                item.get("LONG_NAME") or item.get("longName") or
                item.get("scrip_name") or item.get("Issuer_Name") or ""
            ).strip().title()
            isin = (
                item.get("ISIN_NO") or item.get("isinNumber") or item.get("ISIN") or ""
            ).strip()
            sector = (item.get("INDUSTRY") or item.get("industry") or "").strip().title()

            if not bse_code or not name:
                continue

            # If BSE record has an NSE symbol, update that document; otherwise key by BSE code
            if nse_sym:
                ops.append(UpdateOne(
                    {"symbol": nse_sym},
                    {"$set": {
                        "bse_code": bse_code, "isin": isin,
                        "sector": sector, "bse_listed": True, "active": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }},
                    upsert=False,  # only update existing NSE record
                ))
                # Also ensure a doc exists if NSE sync missed it
                ops.append(UpdateOne(
                    {"symbol": nse_sym},
                    {"$setOnInsert": {
                        "symbol": nse_sym, "name": name, "bse_code": bse_code,
                        "isin": isin, "sector": sector,
                        "nse_listed": False, "bse_listed": True, "active": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }},
                    upsert=True,
                ))
            else:
                # BSE-only listing — key by BSE code
                ops.append(UpdateOne(
                    {"bse_code": bse_code},
                    {"$set": {
                        "symbol": f"BSE_{bse_code}", "name": name,
                        "bse_code": bse_code, "isin": isin, "sector": sector,
                        "nse_listed": False, "bse_listed": True, "active": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }},
                    upsert=True,
                ))
            count += 1

        for i in range(0, len(ops), 500):
            await companies_col.bulk_write(ops[i:i+500])

        logger.info(f"BSE sync complete: {count} records processed")
    except Exception as e:
        logger.error(f"BSE company sync failed: {e}")
    return count


async def ensure_indexes():
    await companies_col.create_index("symbol")
    await companies_col.create_index("bse_code")
    await companies_col.create_index("isin")
    # Text index for full-text search on name + symbol
    await companies_col.create_index([("name", "text"), ("symbol", "text")])
    await analyses_col.create_index("analysis_id")
    await analyses_col.create_index("user_id")
    await users_col.create_index("email", unique=True)
    logger.info("MongoDB indexes ensured")


async def initial_sync():
    """Run on startup: sync if DB is empty or data is stale (>24h)."""
    await ensure_indexes()
    count = await companies_col.count_documents({})
    if count == 0:
        logger.info("Company master empty — running full NSE + BSE sync...")
        n = await sync_nse_companies()
        b = await sync_bse_companies()
        logger.info(f"Initial sync done — NSE: {n}, BSE: {b}")
    else:
        latest = await companies_col.find_one({}, sort=[("updated_at", -1)])
        if latest:
            try:
                updated  = datetime.fromisoformat(latest["updated_at"])
                age_hrs  = (datetime.utcnow() - updated).total_seconds() / 3600
            except Exception:
                age_hrs = 999
            if age_hrs > 24:
                logger.info(f"Data is {age_hrs:.0f}h old — scheduling background refresh")
                asyncio.create_task(sync_nse_companies())
                asyncio.create_task(sync_bse_companies())
            else:
                logger.info(f"Company master: {count:,} records, last synced {age_hrs:.1f}h ago ✓")


async def _daily_sync_loop():
    """Background task: re-sync every 24 hours."""
    while True:
        await asyncio.sleep(86400)
        logger.info("Daily scheduled company sync starting...")
        await sync_nse_companies()
        await sync_bse_companies()


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(initial_sync())
    asyncio.create_task(_daily_sync_loop())


# ── COMPANY SEARCH ────────────────────────────────────────────────────────────
async def search_companies(query: str, limit: int = 15) -> List[dict]:
    """Multi-pass search: exact symbol → symbol prefix → name prefix → name contains."""
    q_upper = query.strip().upper()
    q_orig  = query.strip()
    results: List[dict] = []
    seen: set = set()

    def _add(doc: dict, score: int):
        doc.pop("_id", None)
        key = doc.get("symbol") or doc.get("bse_code", "")
        if key and key not in seen:
            seen.add(key)
            results.append({**doc, "_score": score})

    # 1. Exact symbol
    doc = await companies_col.find_one({"symbol": q_upper})
    if doc: _add(doc, 100)

    # 2. Symbol starts-with
    async for doc in companies_col.find(
        {"symbol": {"$regex": f"^{re.escape(q_upper)}", "$options": "i"}}, limit=10
    ):
        _add(doc, 80)

    # 3. Name starts-with
    async for doc in companies_col.find(
        {"name": {"$regex": f"^{re.escape(q_orig)}", "$options": "i"}}, limit=10
    ):
        _add(doc, 60)

    # 4. Name contains
    if len(results) < limit:
        async for doc in companies_col.find(
            {"name": {"$regex": re.escape(q_orig), "$options": "i"}}, limit=limit
        ):
            _add(doc, 40)

    results.sort(key=lambda x: -x.pop("_score", 0))
    return results[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
#  PDF EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════
def extract_pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages  = [p.extract_text() or "" for p in reader.pages]
        text   = "\n\n".join(p for p in pages if p.strip())
        logger.info(f"Extracted {len(text)} chars from {len(reader.pages)}-page PDF")
        return text
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  ROBUST JSON PARSER  (handles fences, truncation, extra data)
# ═══════════════════════════════════════════════════════════════════════════════
def extract_and_parse_json(raw: str) -> dict:
    # Strip markdown fences
    raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found. Preview: {raw[:300]}")

    # Walk to find matching closing brace (respects strings and escapes)
    depth = 0
    end   = -1
    in_str   = False
    esc_next = False

    for i, ch in enumerate(raw[start:], start=start):
        if esc_next:        esc_next = False; continue
        if ch == "\\" and in_str: esc_next = True; continue
        if ch == '"':       in_str = not in_str; continue
        if in_str:          continue
        if ch == "{":       depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:  end = i + 1; break

    json_str = raw[start:end] if end != -1 else _repair_truncated_json(raw[start:])

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error at {e.pos}: {e.msg} — attempting repair")
        return json.loads(_repair_truncated_json(json_str))


def _repair_truncated_json(s: str) -> str:
    # Remove last incomplete key-value pair
    last_comma = s.rfind(",")
    if last_comma > len(s) // 2:
        s = s[:last_comma]

    # Count unclosed braces/brackets
    d_brace = d_bracket = 0
    in_str = esc = False
    for ch in s:
        if esc:         esc = False; continue
        if ch == "\\":  esc = True; continue
        if ch == '"':   in_str = not in_str; continue
        if in_str:      continue
        if ch == "{":   d_brace += 1
        elif ch == "}": d_brace -= 1
        elif ch == "[": d_bracket += 1
        elif ch == "]": d_bracket -= 1

    s = s.rstrip().rstrip(",")
    s += "]" * max(d_bracket, 0)
    s += "}" * max(d_brace, 0)
    return s


# ═══════════════════════════════════════════════════════════════════════════════
#  AI PROMPT  (capped at 10k chars to leave headroom for JSON output)
# ═══════════════════════════════════════════════════════════════════════════════
def build_prompt(text: str) -> str:
    return f"""You are a world-class senior financial analyst (CFA, 20+ years).
Analyse this financial document and return ONLY valid JSON. No markdown, no code blocks, no explanation.

RULES:
- Use EXACT numbers from the document.
- Score components must sum to health_score total.
- Use "N/A" only if data is genuinely missing.
- Return ONLY the JSON object — nothing before or after it.

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
      {{"category": "Profitability",      "weight": 30, "score": 22, "max": 30, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers"}},
      {{"category": "Revenue Growth",     "weight": 25, "score": 18, "max": 25, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers"}},
      {{"category": "Debt & Leverage",    "weight": 20, "score": 14, "max": 20, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers"}},
      {{"category": "Liquidity",          "weight": 15, "score": 12, "max": 15, "rating": "Strong/Moderate/Weak", "reasoning": "exact numbers"}},
      {{"category": "Management Outlook", "weight": 10, "score":  9, "max": 10, "rating": "Strong/Moderate/Weak", "reasoning": "tone and guidance"}}
    ]
  }},
  "executive_summary": "5-6 comprehensive sentences",
  "investor_verdict": "3-4 sentences plain English for a non-finance reader",
  "key_metrics": [
    {{"label": "Revenue / Total Income", "current": "val", "previous": "val", "change": "+X% YoY", "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Net Profit / PAT",       "current": "val", "previous": "val", "change": "+X%",     "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA",                 "current": "val", "previous": "val", "change": "+X%",     "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EBITDA Margin",          "current": "X%",  "previous": "X%",  "change": "+X bps",  "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "EPS (Basic)",            "current": "val", "previous": "val", "change": "val",     "trend": "up/down/neutral", "comment": "context"}},
    {{"label": "Total Debt",             "current": "val", "previous": "val", "change": "val",     "trend": "down",            "comment": "context"}},
    {{"label": "ROE",                    "current": "X%",  "previous": "X%",  "change": "val",     "trend": "up",              "comment": "context"}},
    {{"label": "Debt to Equity",         "current": "val", "previous": "val", "change": "val",     "trend": "down",            "comment": "context"}},
    {{"label": "Operating Cash Flow",    "current": "val", "previous": "val", "change": "val",     "trend": "up",              "comment": "context"}}
  ],
  "profitability": {{
    "analysis": "3-4 sentences with exact numbers",
    "gross_margin_current": "X%",  "gross_margin_previous": "X%",
    "net_margin_current": "X%",    "net_margin_previous": "X%",
    "ebitda_margin_current": "X%", "ebitda_margin_previous": "X%",
    "roe": "X%", "roa": "X%",
    "key_cost_drivers": ["Item with number", "Item 2"]
  }},
  "growth": {{
    "analysis": "3-4 sentences",
    "revenue_growth_yoy": "X%", "profit_growth_yoy": "X%",
    "volume_growth": "X% or N/A", "guidance": "guidance text or N/A"
  }},
  "liquidity": {{
    "analysis": "2-3 sentences", "current_ratio": "val", "quick_ratio": "val",
    "cash_position": "val", "operating_cash_flow": "val", "free_cash_flow": "val"
  }},
  "debt": {{
    "analysis": "2-3 sentences", "total_debt": "val", "debt_to_equity": "val",
    "interest_coverage": "val", "net_debt": "val",
    "debt_trend": "Decreasing/Increasing/Stable"
  }},
  "management_commentary": {{
    "overall_tone": "Positive/Cautious/Neutral/Concerned",
    "key_points": ["Point 1","Point 2","Point 3","Point 4","Point 5"],
    "outlook_statement": "what management said",
    "concerns_raised": ["Concern 1","Concern 2"]
  }},
  "segments": [{{"name":"Segment","revenue":"val","growth":"X%","margin":"X%","comment":"observation"}}],
  "highlights":    ["Strength 1 with numbers","Strength 2","Strength 3","Strength 4"],
  "risks":         ["Risk 1 with context","Risk 2","Risk 3"],
  "what_to_watch": ["Item 1","Item 2","Item 3"]
}}

DOCUMENT:
{text[:10000]}"""


# ═══════════════════════════════════════════════════════════════════════════════
#  AI RUNNERS
# ═══════════════════════════════════════════════════════════════════════════════
def _sync_gemini(text: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config={"temperature": 0.1, "max_output_tokens": 4096},
    )
    resp = model.generate_content(build_prompt(text))
    logger.info(f"Gemini response: {len(resp.text)} chars")
    return extract_and_parse_json(resp.text)


def _sync_groq(text: str) -> dict:
    from groq import Groq
    gc = Groq(api_key=GROQ_API_KEY)
    resp = gc.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": build_prompt(text)}],
        temperature=0.1,
        max_tokens=4096,
    )
    # SDK returns a Python object — extract the text string first
    raw = resp.choices[0].message.content
    logger.info(f"Groq response: {len(raw)} chars")
    return extract_and_parse_json(raw)


async def run_analysis(text: str) -> dict:
    loop   = asyncio.get_event_loop()
    errors: List[str] = []

    if GEMINI_API_KEY:
        try:
            result = await loop.run_in_executor(executor, _sync_gemini, text)
            logger.info("✓ Gemini analysis succeeded")
            return result
        except Exception as e:
            logger.warning(f"Gemini failed: {e}")
            errors.append(f"Gemini: {str(e)[:120]}")

    if GROQ_API_KEY:
        try:
            result = await loop.run_in_executor(executor, _sync_groq, text)
            logger.info("✓ Groq analysis succeeded")
            return result
        except Exception as e:
            logger.error(f"Groq failed: {e}")
            errors.append(f"Groq: {str(e)[:120]}")

    raise Exception(
        "AI analysis failed. "
        + (" | ".join(errors) if errors else "No API keys configured.")
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  FILING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _classify_filing(title: str) -> str:
    t = title.lower()
    if "annual" in t:                                              return "Annual Report"
    if "q1" in t or "first quarter" in t or "june" in t:          return "Q1 Results"
    if "q2" in t or "second quarter" in t or "september" in t:    return "Q2 Results"
    if "q3" in t or "third quarter" in t or "december" in t:      return "Q3 Results"
    if "q4" in t or "fourth quarter" in t or "march" in t:        return "Q4 Results"
    if "half" in t or "h1" in t or "h2" in t:                     return "Half-Year Results"
    if "result" in t or "financial" in t:                          return "Financial Results"
    return "Filing"


async def fetch_nse_filings(symbol: str) -> List[dict]:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)

            r = await client.get(
                f"https://www.nseindia.com/api/annual-reports"
                f"?symbol={symbol}&issuer={symbol}&type=annual-report",
                headers=NSE_HEADERS,
            )
            if r.status_code == 200:
                data  = r.json()
                items = data.get("data") or (data if isinstance(data, list) else [])
                filings = []
                for item in items:
                    pdf = (item.get("fileName") or item.get("pdfName") or item.get("attachment") or "").strip()
                    if not pdf: continue
                    if not pdf.startswith("http"):
                        pdf = f"https://www.nseindia.com/corporate-governance/annexure/{pdf}"
                    filings.append({
                        "title": item.get("subject") or item.get("fileDesc") or "Annual Report",
                        "date": item.get("dt") or item.get("sort_date") or "",
                        "pdf_url": pdf, "type": "Annual Report", "source": "NSE", "symbol": symbol,
                    })
                if filings: return filings[:10]

            # Fallback: announcements
            r2 = await client.get(
                f"https://www.nseindia.com/api/corporates-announcements"
                f"?index=equities&symbol={symbol}&category=annual-report",
                headers=NSE_HEADERS,
            )
            if r2.status_code == 200:
                data2  = r2.json()
                items2 = data2.get("data", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
                filings = []
                for item in items2[:20]:
                    pdf   = (item.get("attchmntFile") or item.get("attachment") or "").strip()
                    title = item.get("subject") or item.get("desc") or "Filing"
                    if not pdf: continue
                    if not pdf.startswith("http"):
                        pdf = f"https://www.nseindia.com/{pdf.lstrip('/')}"
                    filings.append({
                        "title": title,
                        "date": item.get("an_dt") or item.get("dt") or "",
                        "pdf_url": pdf, "type": _classify_filing(title), "source": "NSE", "symbol": symbol,
                    })
                if filings: return filings[:10]
    except Exception as e:
        logger.warning(f"NSE filings error for {symbol}: {e}")
    return []


async def verify_pdf_url(client: httpx.AsyncClient, url: str) -> bool:
    """
    HEAD-check a PDF URL to confirm it actually exists (not 404/403).
    Falls back to GET if HEAD is not supported.
    """
    try:
        r = await client.head(url, headers=BSE_HEADERS, timeout=8)
        if r.status_code == 405:  # HEAD not allowed — try GET with range
            r = await client.get(url, headers={**BSE_HEADERS, "Range": "bytes=0-10"}, timeout=8)
        return r.status_code in (200, 206)
    except Exception:
        return False


async def fetch_bse_filings(bse_code: str, symbol: str) -> List[dict]:
    if not bse_code:
        return []
    try:
        from datetime import date as _date
        to_dt   = _date.today().strftime("%Y%m%d")
        from_dt = (_date.today() - timedelta(days=1460)).strftime("%Y%m%d")

        def _bse_url(cat: str) -> str:
            return (
                f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
                f"?pageno=1&strCat={cat}&strPrevDate={from_dt}&strScrip={bse_code}"
                f"&strSearch=P&strToDate={to_dt}&strType=C"
            )

        # BSE stores PDFs in two possible locations
        def _pdf_urls(pdf_name: str) -> List[str]:
            return [
                f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{pdf_name}",
                f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{pdf_name}",
            ]

        filings: List[dict] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # Warm BSE session
            await client.get("https://www.bseindia.com/", headers=BSE_HEADERS)

            for cat, max_items in [("Result", 15), ("Annual+Report", 5)]:
                r = await client.get(_bse_url(cat), headers=BSE_HEADERS)
                if r.status_code != 200:
                    continue

                for item in (r.json().get("Table", []))[:max_items]:
                    pdf_name = item.get("ATTACHMENTNAME", "").strip()
                    if not pdf_name:
                        continue

                    title = item.get("SUBJECT", item.get("CATEGORYNAME", "Financial Results"))

                    # Try both AttachLive and AttachHis locations
                    working_url = None
                    for candidate_url in _pdf_urls(pdf_name):
                        if await verify_pdf_url(client, candidate_url):
                            working_url = candidate_url
                            break

                    if not working_url:
                        logger.warning(f"BSE PDF not found for {pdf_name} — skipping")
                        continue

                    filings.append({
                        "title": title,
                        "date": item.get("NEWS_DT", ""),
                        "pdf_url": working_url,
                        "type": "Annual Report" if cat == "Annual+Report" else _classify_filing(title),
                        "source": "BSE", "symbol": symbol, "bse_code": bse_code,
                    })

        logger.info(f"BSE: found {len(filings)} valid filings for {bse_code}")
        return filings[:12]
    except Exception as e:
        logger.warning(f"BSE filings error for {bse_code}: {e}")
    return []


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — HEALTH + ADMIN
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/health")
async def health():
    company_count = await companies_col.count_documents({})
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "gemini": bool(GEMINI_API_KEY),
        "groq": bool(GROQ_API_KEY),
        "companies_in_db": company_count,
    }

@app.post("/api/admin/sync-companies")
async def trigger_sync():
    """Manually trigger a full re-sync of the company master from NSE + BSE."""
    asyncio.create_task(sync_nse_companies())
    asyncio.create_task(sync_bse_companies())
    return {"status": "sync started in background"}

@app.get("/api/admin/sync-status")
async def sync_status():
    count  = await companies_col.count_documents({})
    latest = await companies_col.find_one({}, sort=[("updated_at", -1)])
    return {
        "total_companies": count,
        "last_updated": latest.get("updated_at") if latest else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — AUTH
# ═══════════════════════════════════════════════════════════════════════════════
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
    await users_col.insert_one({
        "user_id": uid, "name": req.name.strip(), "email": email,
        "password": hash_pw(req.password), "created_at": datetime.utcnow().isoformat(),
    })
    return {"token": create_token(uid), "user_id": uid, "name": req.name.strip(), "email": email}

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    if not req.email.strip() or not req.password:
        raise HTTPException(400, "Email and password required")
    email = req.email.strip().lower()
    user  = await users_col.find_one({"email": email})
    if not user:
        raise HTTPException(401, "No account with this email. Please register first.")
    if not verify_pw(req.password, user["password"]):
        raise HTTPException(401, "Incorrect password")
    return {
        "token": create_token(user["user_id"]),
        "user_id": user["user_id"], "name": user["name"], "email": user["email"],
    }

@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — COMPANY SEARCH
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/nse/search")
async def nse_search(q: str = ""):
    if not q.strip():
        return {"results": [], "query": ""}
    results = await search_companies(q, limit=15)
    return {"results": results, "query": q, "total": len(results)}

@app.get("/api/nse/popular")
async def nse_popular():
    """Return large-cap, high-volume popular companies."""
    popular = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
        "BAJFINANCE", "ZOMATO", "LT", "WIPRO", "ADANIENT", "TATAMOTORS",
        "HINDUNILVR", "ITC", "AXISBANK",
    ]
    results = []
    for sym in popular:
        doc = await companies_col.find_one({"symbol": sym})
        if doc:
            doc.pop("_id", None)
            results.append(doc)
    return {"results": results}


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — FILINGS
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/filings/{symbol}")
async def get_filings(symbol: str):
    symbol  = symbol.upper().strip()
    company = await companies_col.find_one({"symbol": symbol})
    if not company:
        raise HTTPException(
            404,
            f"Company '{symbol}' not found. "
            f"Try searching: /api/nse/search?q={symbol}"
        )

    bse_code = company.get("bse_code", "")
    results  = await asyncio.gather(
        fetch_nse_filings(symbol),
        fetch_bse_filings(bse_code, symbol),
        return_exceptions=True,
    )
    nse_filings = results[0] if isinstance(results[0], list) else []
    bse_filings = results[1] if isinstance(results[1], list) else []

    all_filings = bse_filings + nse_filings  # BSE first (generally more complete)
    seen: set = set()
    unique: List[dict] = []
    for f in all_filings:
        key = f["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)

    def _parse_date(d: str):
        for fmt in ["%d %b %Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y"]:
            try: return datetime.strptime((d or "").strip(), fmt)
            except ValueError: pass
        return datetime.min

    unique.sort(key=lambda x: _parse_date(x.get("date", "")), reverse=True)

    return {
        "symbol":   symbol,
        "company":  company.get("name", symbol),
        "sector":   company.get("sector", ""),
        "isin":     company.get("isin", ""),
        "bse_code": bse_code,
        "filings":  unique[:15],
        "total":    len(unique),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — ANALYZE (upload)
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), user=Depends(get_optional_user)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    filename    = file.filename or "document.pdf"
    analysis_id = str(uuid.uuid4())
    user_id     = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"

    await analyses_col.insert_one({
        "analysis_id": analysis_id, "user_id": user_id, "is_guest": user is None,
        "filename": filename, "status": "processing",
        "created_at": datetime.utcnow().isoformat(), "result": None,
    })
    try:
        loop = asyncio.get_event_loop()
        text = (
            await loop.run_in_executor(executor, extract_pdf_text, content)
            if filename.lower().endswith(".pdf")
            else f"Image document: {filename}"
        )
        if not text or len(text.strip()) < 30:
            text = f"[Minimal text extracted from {filename}]"

        result = await run_analysis(text)
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "completed", "result": result}},
        )
        return {"analysis_id": analysis_id, "status": "completed", "result": result}
    except Exception as e:
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "failed", "message": str(e)}},
        )
        return {"analysis_id": analysis_id, "status": "failed", "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — ANALYZE FROM URL
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/analyze-from-url")
async def analyze_from_url(req: AnalyzeFromURLRequest, user=Depends(get_optional_user)):
    analysis_id = str(uuid.uuid4())
    user_id     = user["user_id"] if user else f"guest_{str(uuid.uuid4())[:8]}"

    await analyses_col.insert_one({
        "analysis_id": analysis_id, "user_id": user_id, "is_guest": user is None,
        "filename": req.filename, "source": req.source, "pdf_url": req.pdf_url,
        "status": "processing", "created_at": datetime.utcnow().isoformat(), "result": None,
    })
    try:
        logger.info(f"Fetching PDF: {req.pdf_url}")
        headers = NSE_HEADERS if req.source == "nse" else BSE_HEADERS

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            if req.source == "nse":
                await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
            elif req.source == "bse":
                await client.get("https://www.bseindia.com/", headers=BSE_HEADERS)
            r = await client.get(req.pdf_url, headers=headers)

        if r.status_code != 200:
            raise Exception(f"Could not fetch PDF (HTTP {r.status_code})")
        if "pdf" not in r.headers.get("content-type", "").lower() and len(r.content) < 1000:
            raise Exception("Response does not appear to be a valid PDF")

        logger.info(f"Downloaded {len(r.content):,} bytes from {req.source}")

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(executor, extract_pdf_text, r.content)

        if not text or len(text.strip()) < 50:
            raise Exception("Could not extract text — PDF may be scanned/image-based")

        result = await run_analysis(text)
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "completed", "result": result}},
        )
        logger.info(f"✓ URL analysis done: {analysis_id}")
        return {"analysis_id": analysis_id, "status": "completed", "result": result}

    except Exception as e:
        msg = str(e)
        logger.error(f"✗ URL analysis failed {analysis_id}: {msg}")
        await analyses_col.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "failed", "message": msg}},
        )
        return {"analysis_id": analysis_id, "status": "failed", "message": msg}


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES — ANALYSES CRUD
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/public/analyses/{analysis_id}")
async def public_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id": analysis_id})
    if not doc or doc.get("status") != "completed":
        raise HTTPException(404, "Analysis not found")
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc

@app.get("/api/analyses")
async def list_analyses(user=Depends(get_current_user)):
    docs = []
    async for doc in analyses_col.find({"user_id": user["user_id"]}).sort("created_at", -1):
        doc.pop("_id", None)
        docs.append(doc)
    return docs

@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id": analysis_id})
    if not doc:
        raise HTTPException(404, "Analysis not found")
    doc.pop("_id", None)
    return doc

@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str, user=Depends(get_current_user)):
    r = await analyses_col.delete_one({"analysis_id": analysis_id, "user_id": user["user_id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Analysis not found or does not belong to you")
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════════════
#  PDF EXPORT  — converts analysis result to a styled PDF via WeasyPrint
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/analyses/{analysis_id}/export-pdf")
async def export_pdf(analysis_id: str):
    doc = await analyses_col.find_one({"analysis_id": analysis_id})
    if not doc or doc.get("status") != "completed":
        raise HTTPException(404, "Analysis not found")

    result = doc.get("result", {})
    filename = doc.get("filename", "report").replace(".pdf", "")

    html = _build_report_html(result)

    loop = asyncio.get_event_loop()
    pdf_bytes = await loop.run_in_executor(executor, _render_pdf, html)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}_finsight.pdf"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


def _render_pdf(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


def _build_report_html(r: dict) -> str:
    def val(v):
        return v if v and v != "N/A" else "—"

    # Build metrics rows
    metrics_rows = ""
    for m in r.get("key_metrics", []):
        trend = m.get("trend", "neutral")
        arrow = "▲" if trend == "up" else ("▼" if trend == "down" else "●")
        color = "#16a34a" if trend == "up" else ("#dc2626" if trend == "down" else "#6b7280")
        metrics_rows += f"""
        <tr>
            <td>{val(m.get('label'))}</td>
            <td><strong>{val(m.get('current'))}</strong></td>
            <td>{val(m.get('previous'))}</td>
            <td style="color:{color}">{arrow} {val(m.get('change'))}</td>
            <td style="color:#6b7280;font-size:11px">{val(m.get('comment'))}</td>
        </tr>"""

    # Score breakdown
    score_rows = ""
    for c in r.get("health_score_breakdown", {}).get("components", []):
        pct = int((c.get("score", 0) / c.get("max", 1)) * 100)
        bar_color = "#16a34a" if pct >= 70 else ("#f59e0b" if pct >= 40 else "#dc2626")
        score_rows += f"""
        <tr>
            <td>{val(c.get('category'))}</td>
            <td>{c.get('score')}/{c.get('max')}</td>
            <td>{c.get('rating','')}</td>
            <td>
                <div style="background:#e5e7eb;border-radius:4px;height:8px;width:120px">
                    <div style="background:{bar_color};width:{pct}%;height:8px;border-radius:4px"></div>
                </div>
            </td>
            <td style="color:#6b7280;font-size:10px">{val(c.get('reasoning'))}</td>
        </tr>"""

    # Highlights, risks, what to watch
    def bullet_list(items):
        return "".join(f"<li>{i}</li>" for i in (items or []))

    # Management key points
    mgmt = r.get("management_commentary", {})
    mgmt_points = bullet_list(mgmt.get("key_points", []))
    concerns     = bullet_list(mgmt.get("concerns_raised", []))

    # Segments
    segment_rows = ""
    for s in r.get("segments", []):
        segment_rows += f"""
        <tr>
            <td>{val(s.get('name'))}</td>
            <td>{val(s.get('revenue'))}</td>
            <td>{val(s.get('growth'))}</td>
            <td>{val(s.get('margin'))}</td>
            <td style="color:#6b7280;font-size:11px">{val(s.get('comment'))}</td>
        </tr>"""

    health = r.get("health_score", 0)
    health_color = (
        "#16a34a" if health >= 75 else
        "#65a30d" if health >= 60 else
        "#f59e0b" if health >= 45 else
        "#dc2626"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: Inter, Arial, sans-serif; font-size:13px; color:#1f2937; background:#fff; }}
  .page {{ padding: 40px 48px; }}

  /* Header */
  .header {{ display:flex; justify-content:space-between; align-items:flex-start;
             border-bottom:3px solid #2563eb; padding-bottom:20px; margin-bottom:28px; }}
  .header-left h1 {{ font-size:22px; font-weight:700; color:#1e3a8a; }}
  .header-left p  {{ font-size:12px; color:#6b7280; margin-top:4px; }}
  .score-badge {{ text-align:center; background:{health_color}; color:#fff;
                  border-radius:12px; padding:12px 20px; }}
  .score-badge .num {{ font-size:36px; font-weight:700; line-height:1; }}
  .score-badge .lbl {{ font-size:11px; margin-top:2px; }}

  /* Meta */
  .meta-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }}
  .meta-box {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px; }}
  .meta-box .label {{ font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.5px; }}
  .meta-box .value {{ font-size:13px; font-weight:600; color:#1e293b; margin-top:4px; }}

  /* Sections */
  .section {{ margin-bottom:24px; }}
  .section-title {{ font-size:14px; font-weight:700; color:#1e3a8a;
                    border-left:4px solid #2563eb; padding-left:10px; margin-bottom:12px; }}

  /* Summary boxes */
  .summary-box {{ background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px;
                  padding:14px; margin-bottom:12px; line-height:1.7; color:#1e3a8a; }}
  .verdict-box  {{ background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px;
                   padding:14px; line-height:1.7; color:#14532d; }}

  /* Tables */
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ background:#1e3a8a; color:#fff; padding:8px 10px; text-align:left; font-weight:600; }}
  td {{ padding:7px 10px; border-bottom:1px solid #f1f5f9; vertical-align:top; }}
  tr:nth-child(even) td {{ background:#f8fafc; }}

  /* Two col */
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}

  /* Lists */
  ul {{ padding-left:18px; line-height:1.9; }}
  ul li {{ color:#374151; }}

  /* Footer */
  .footer {{ margin-top:32px; border-top:1px solid #e5e7eb; padding-top:12px;
             font-size:10px; color:#9ca3af; display:flex; justify-content:space-between; }}

  /* Page break */
  .break {{ page-break-before: always; }}
</style>
</head>
<body>
<div class="page">

  <!-- HEADER -->
  <div class="header">
    <div class="header-left">
      <h1>FinSight Financial Analysis Report</h1>
      <p>{val(r.get('company_name'))} &nbsp;|&nbsp; {val(r.get('period'))} &nbsp;|&nbsp; {val(r.get('statement_type'))}</p>
      <p style="margin-top:6px;color:#94a3b8;font-size:11px">Generated on {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}</p>
    </div>
    <div class="score-badge">
      <div class="num">{health}</div>
      <div class="lbl">Health Score</div>
      <div style="font-size:12px;margin-top:4px;font-weight:600">{val(r.get('health_label'))}</div>
    </div>
  </div>

  <!-- META -->
  <div class="meta-grid">
    <div class="meta-box"><div class="label">Company</div><div class="value">{val(r.get('company_name'))}</div></div>
    <div class="meta-box"><div class="label">Period</div><div class="value">{val(r.get('period'))}</div></div>
    <div class="meta-box"><div class="label">Report Type</div><div class="value">{val(r.get('statement_type'))}</div></div>
    <div class="meta-box"><div class="label">Currency</div><div class="value">{val(r.get('currency'))}</div></div>
  </div>

  <!-- SUMMARY -->
  <div class="section">
    <div class="section-title">Executive Summary</div>
    <div class="summary-box">{val(r.get('executive_summary'))}</div>
    <div class="verdict-box"><strong>Investor Verdict:</strong> {val(r.get('investor_verdict'))}</div>
  </div>

  <!-- SCORE BREAKDOWN -->
  <div class="section">
    <div class="section-title">Health Score Breakdown</div>
    <table>
      <tr><th>Category</th><th>Score</th><th>Rating</th><th>Progress</th><th>Reasoning</th></tr>
      {score_rows}
    </table>
  </div>

  <!-- KEY METRICS -->
  <div class="section break">
    <div class="section-title">Key Financial Metrics</div>
    <table>
      <tr><th>Metric</th><th>Current</th><th>Previous</th><th>Change</th><th>Comment</th></tr>
      {metrics_rows}
    </table>
  </div>

  <!-- PROFITABILITY + GROWTH -->
  <div class="two-col section">
    <div>
      <div class="section-title">Profitability</div>
      <div class="summary-box" style="font-size:12px">{val((r.get('profitability') or {}).get('analysis'))}</div>
    </div>
    <div>
      <div class="section-title">Growth</div>
      <div class="summary-box" style="font-size:12px">{val((r.get('growth') or {}).get('analysis'))}</div>
    </div>
  </div>

  <!-- LIQUIDITY + DEBT -->
  <div class="two-col section">
    <div>
      <div class="section-title">Liquidity</div>
      <div class="summary-box" style="font-size:12px">{val((r.get('liquidity') or {}).get('analysis'))}</div>
    </div>
    <div>
      <div class="section-title">Debt & Leverage</div>
      <div class="summary-box" style="font-size:12px">{val((r.get('debt') or {}).get('analysis'))}</div>
    </div>
  </div>

  <!-- SEGMENTS -->
  {f'''<div class="section">
    <div class="section-title">Business Segments</div>
    <table>
      <tr><th>Segment</th><th>Revenue</th><th>Growth</th><th>Margin</th><th>Comment</th></tr>
      {segment_rows}
    </table>
  </div>''' if segment_rows else ''}

  <!-- MANAGEMENT -->
  <div class="section break">
    <div class="section-title">Management Commentary — Tone: {val(mgmt.get('overall_tone'))}</div>
    <div class="two-col">
      <div>
        <strong style="font-size:12px">Key Points</strong>
        <ul style="margin-top:8px;font-size:12px">{mgmt_points}</ul>
      </div>
      <div>
        <strong style="font-size:12px">Concerns Raised</strong>
        <ul style="margin-top:8px;font-size:12px">{concerns}</ul>
        <div style="margin-top:12px;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:10px;font-size:11px">
          <strong>Outlook:</strong> {val(mgmt.get('outlook_statement'))}
        </div>
      </div>
    </div>
  </div>

  <!-- HIGHLIGHTS + RISKS + WATCH -->
  <div class="section">
    <div class="two-col">
      <div>
        <div class="section-title">Key Highlights</div>
        <ul style="font-size:12px">{bullet_list(r.get('highlights', []))}</ul>
      </div>
      <div>
        <div class="section-title">Key Risks</div>
        <ul style="font-size:12px;color:#dc2626">{bullet_list(r.get('risks', []))}</ul>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">What to Watch Next</div>
    <ul style="font-size:12px">{bullet_list(r.get('what_to_watch', []))}</ul>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <span>FinSight AI — Automated Financial Analysis</span>
    <span>For informational purposes only. Not financial advice.</span>
    <span>{datetime.utcnow().strftime('%d %b %Y')}</span>
  </div>

</div>
</body>
</html>"""
