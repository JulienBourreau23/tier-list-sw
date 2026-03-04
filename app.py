import os
from typing import Optional
from fastapi import FastAPI, Query, HTTPException, Security, Depends
from fastapi.responses import FileResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

PG_DSN = os.getenv("PG_DSN")
ICON_DIR = os.getenv("ICON_DIR", "/srv/sw_coaching/icons/monsters")
FALLBACK_ICON = os.getenv("FALLBACK_ICON", os.path.join(ICON_DIR, "missing.png"))
API_KEY = os.getenv("API_SECRET_KEY")  # ← nouveau

if not PG_DSN:
    raise RuntimeError("PG_DSN manquant (ex: postgresql://user:pass@host:5432/sw_coaching)")

app = FastAPI(title="TierList API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*", "X-API-Key"],  # ← autorise le header de clé
)

# ── Sécurité API Key ─────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(key: str = Security(api_key_header)):
    """Si API_SECRET_KEY est définie dans le .env, elle est obligatoire."""
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=403, detail="Clé API invalide ou manquante")

# ── DB ───────────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(PG_DSN)

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Route publique — pas de clé requise (utile pour les healthchecks)."""
    return {"ok": True}


@app.get("/api/monsters", dependencies=[Depends(verify_api_key)])
def list_monsters(
    stars: Optional[str] = Query(default=None, description="Ex: '4,5'"),
    elements: Optional[str] = Query(default=None, description="Ex: 'Fire,Water,Wind' ou 'Light,Dark'"),
    q: Optional[str] = Query(default=None, description="Recherche texte dans nom_en"),
    awaken_level: Optional[int] = Query(default=None, description="Niveau d'awakening (ex: 2 pour les monstres 2A)"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    where = ["base_stars != natural_stars", "obtainable = true"]
    params = {}

    if stars:
        star_list = [int(x.strip()) for x in stars.split(",") if x.strip().isdigit()]
        if star_list:
            where.append("natural_stars = ANY(%(stars)s)")
            params["stars"] = star_list

    if elements:
        el_list = [x.strip() for x in elements.split(",") if x.strip()]
        if el_list:
            where.append("element = ANY(%(elements)s)")
            params["elements"] = el_list

    if q:
        where.append("nom_en ILIKE %(q)s")
        params["q"] = f"%{q}%"

    if awaken_level is not None:
        where.append("awaken_level = %(awaken_level)s")
        params["awaken_level"] = awaken_level

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT
            com2us_id,
            nom_en,
            element,
            archetype,
            natural_stars,
            base_stars
        FROM monstres
        {where_sql}
        ORDER BY natural_stars DESC, nom_en ASC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    params["limit"] = limit
    params["offset"] = offset

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    base_url = os.getenv("PUBLIC_BASE_URL", "")
    for r in rows:
        r["icon_url"] = f"{base_url}/icons/{r['com2us_id']}.png" if base_url else f"/icons/{r['com2us_id']}.png"

    return {"count": len(rows), "results": rows}


@app.get("/api/monsters/{com2us_id}", dependencies=[Depends(verify_api_key)])
def get_monster(com2us_id: int):
    sql = """
        SELECT
            com2us_id,
            nom_en,
            element,
            archetype,
            natural_stars,
            base_stars
        FROM monstres
        WHERE com2us_id = %(com2us_id)s
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"com2us_id": com2us_id})
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Monstre introuvable")

    base_url = os.getenv("PUBLIC_BASE_URL", "")
    row["icon_url"] = f"{base_url}/icons/{row['com2us_id']}.png" if base_url else f"/icons/{row['com2us_id']}.png"

    return row


@app.get("/icons/{com2us_id}.png", dependencies=[Depends(verify_api_key)])
def get_icon(com2us_id: int):
    path = os.path.join(ICON_DIR, f"{com2us_id}.png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return FileResponse(path, media_type="image/png")
    if os.path.exists(FALLBACK_ICON):
        return FileResponse(FALLBACK_ICON, media_type="image/png")
    raise HTTPException(status_code=404, detail="Icon not found")
