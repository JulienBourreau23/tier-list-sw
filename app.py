import os
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
import psycopg2
import psycopg2.extras

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

PG_DSN = os.getenv("PG_DSN")
ICON_DIR = os.getenv("ICON_DIR", "/srv/sw_coaching/icons/monsters")
FALLBACK_ICON = os.getenv("FALLBACK_ICON", os.path.join(ICON_DIR, "missing.png"))

if not PG_DSN:
    raise RuntimeError("PG_DSN manquant (ex: postgresql://user:pass@host:5432/sw_coaching)")

app = FastAPI(title="TierList API", version="0.1")

def get_conn():
    # Connexion simple (suffisant pour démarrer). On optimisera avec pool plus tard si besoin.
    return psycopg2.connect(PG_DSN)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/monsters")
def list_monsters(
    stars: Optional[str] = Query(default=None, description="Ex: '4,5'"),
    elements: Optional[str] = Query(default=None, description="Ex: 'Fire,Water,Wind' ou 'Light,Dark'"),
    q: Optional[str] = Query(default=None, description="Recherche texte dans nom_en"),
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

    # On renvoie aussi un icon_url stable (ton front n’aura qu’à afficher)
    base_url = os.getenv("PUBLIC_BASE_URL", "")  # optionnel (ex: https://tier-list.julien-cloud.eu)
    for r in rows:
        r["icon_url"] = f"{base_url}/icons/{r['com2us_id']}.png" if base_url else f"/icons/{r['com2us_id']}.png"

    return {"count": len(rows), "results": rows}

@app.get("/icons/{com2us_id}.png")
def get_icon(com2us_id: int):
    path = os.path.join(ICON_DIR, f"{com2us_id}.png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return FileResponse(path, media_type="image/png")
    if os.path.exists(FALLBACK_ICON):
        return FileResponse(FALLBACK_ICON, media_type="image/png")
    raise HTTPException(status_code=404, detail="Icon not found")
