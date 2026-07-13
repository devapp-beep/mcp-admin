import logging
import os

from dotenv import load_dotenv

load_dotenv()

if os.getenv("ENV") != "production":
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.cloud import firestore
from starlette.middleware.sessions import SessionMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_EMAILS = {
    e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
}
MCP_SERVERS = [
    s.strip()
    for s in os.getenv(
        "MCP_SERVERS", "rr-mcp,ceipal-mcp,helpjuice-mcp,qb-mcp,nexus-mcp"
    ).split(",")
    if s.strip()
]
COLLECTION = os.getenv("FIRESTORE_COLLECTION", "mcp_access")

app = FastAPI(title="MCP Access Admin")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email"},
)

db = firestore.Client()


def current_email(request: Request) -> str | None:
    return request.session.get("email")


def require_admin(request: Request) -> str:
    email = current_email(request)
    if not email or email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="not authorized")
    return email


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    email = current_email(request)
    if not email:
        return templates.TemplateResponse(request, "login.html")
    if email not in ADMIN_EMAILS:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": f"{email} is signed in but isn't an admin."},
        )

    docs = db.collection(COLLECTION).stream()
    users = []
    for doc in docs:
        data = doc.to_dict() or {}
        users.append({"email": doc.id, "access": data.get("access", [])})
    users.sort(key=lambda u: u["email"])
    response = templates.TemplateResponse(
        request,
        "dashboard.html",
        {"admin": email, "users": users, "servers": MCP_SERVERS},
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/login")
async def login(request: Request):
    redirect_uri = os.environ["BASE_URL"].rstrip("/") + "/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google did not return an email")
    request.session["email"] = email
    return RedirectResponse(url="/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")


@app.post("/users/add")
async def add_user(request: Request, admin: str = Depends(require_admin)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    if email:
        db.collection(COLLECTION).document(email).set({"access": []}, merge=True)
    return RedirectResponse(url="/", status_code=303)


@app.post("/users/{email}/access/toggle")
async def toggle_access(email: str, request: Request, admin: str = Depends(require_admin)):
    form = await request.form()
    server = form.get("server")
    checked = form.get("checked") == "true"

    doc_ref = db.collection(COLLECTION).document(email)
    doc = doc_ref.get()
    access = (doc.to_dict() or {}).get("access", []) if doc.exists else []

    if server == "all":
        access = ["all"] if checked else []
    elif checked:
        access = [a for a in access if a != "all"]
        if server not in access:
            access.append(server)
    else:
        access = [a for a in access if a != server]

    doc_ref.set({"access": access}, merge=True)
    return {"ok": True, "access": access}


@app.post("/users/{email}/delete")
async def delete_user(email: str, admin: str = Depends(require_admin)):
    db.collection(COLLECTION).document(email).delete()
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
