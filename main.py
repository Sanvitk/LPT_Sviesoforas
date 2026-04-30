from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
from datetime import datetime

app = FastAPI()

NKSC_URL = "https://www.nksc.lt/doc/vasaris/siena-lpt.txt"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

legal_domains = set()
illegal_domains = set()
last_nksc_update = None


def normalize(domain: str):
    domain = domain.lower().strip()
    domain = domain.replace("https://", "").replace("http://", "")
    domain = domain.replace("www.", "")
    domain = domain.split("/")[0]
    domain = domain.split("?")[0]
    return domain


def load_domains():
    global legal_domains, illegal_domains

    def load_file(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return set(
                    normalize(line)
                    for line in f
                    if line.strip() and not line.startswith("#")
                )
        except FileNotFoundError:
            return set()

    legal_domains = load_file("legal_domains.txt")
    illegal_domains = load_file("illegal_domains.txt")

    print(f"✔ Loaded legal: {len(legal_domains)}")
    print(f"✔ Loaded illegal local: {len(illegal_domains)}")


async def update_illegal_from_nksc():
    global illegal_domains, last_nksc_update

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(NKSC_URL)
            response.raise_for_status()

        new_domains = set(
            normalize(line)
            for line in response.text.splitlines()
            if line.strip() and not line.startswith("#")
        )

        illegal_domains = new_domains
        last_nksc_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"🌐 NKSC updated: {len(illegal_domains)} domains")

    except Exception as e:
        print("❌ NKSC update failed:", e)


async def background_updater():
    while True:
        await asyncio.sleep(60 * 60 * 6)
        await update_illegal_from_nksc()


@app.on_event("startup")
async def startup_event():
    load_domains()
    await update_illegal_from_nksc()
    asyncio.create_task(background_updater())


def match(domain, domain_set):
    if domain in domain_set:
        return True

    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in domain_set:
            return True

    return False


class DomainRequest(BaseModel):
    domain: str


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "legal_count": len(legal_domains),
        "illegal_count": len(illegal_domains),
        "last_nksc_update": last_nksc_update,
        "source": NKSC_URL,
    }


@app.post("/check-domain")
def check_domain(data: DomainRequest):
    domain = normalize(data.domain)

    if match(domain, legal_domains):
        return {
            "domain": domain,
            "status": "legal",
            "title": "Svetainė yra legali",
            "text": "Ši svetainė rasta licencijuotų domenų sąraše.",
            "basis": "Atitikmuo rastas legalių domenų sąraše.",
            "last_nksc_update": last_nksc_update,
        }

    if match(domain, illegal_domains):
        return {
            "domain": domain,
            "status": "illegal",
            "title": "Svetainė yra nelegali",
            "text": "Ši svetainė rasta nelegalių ar blokuojamų domenų sąraše.",
            "basis": "Atitikmuo rastas nelegalių domenų sąraše.",
            "last_nksc_update": last_nksc_update,
        }

    return {
        "domain": domain,
        "status": "unknown",
        "title": "Svetainės statusas neaiškus",
        "text": "Pagal turimus duomenis svetainė nerasta sąrašuose.",
        "basis": "Atitikmuo nerastas.",
        "last_nksc_update": last_nksc_update,
    }


@app.post("/reload")
async def reload_domains():
    load_domains()
    await update_illegal_from_nksc()
    return {
        "status": "reloaded",
        "legal_count": len(legal_domains),
        "illegal_count": len(illegal_domains),
        "last_nksc_update": last_nksc_update,
    }