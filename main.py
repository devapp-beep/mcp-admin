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

# Per-server tool inventory, for servers where access can be restricted to a
# subset of tools rather than the whole server. Must be kept in sync with the
# tool names each server registers (see that server's tools.py / register()).
SERVER_TOOLS: dict[str, list[str]] = {
    "rr-mcp": [
        "query_cynet_health_run_rate",
        "query_cynet_health_canada_run_rate",
        "query_cynet_locum_run_rate",
        "query_cynet_systems_run_rate",
        "query_cynet_systems_canada_run_rate",
        "query_egov_solutions_run_rate",
    ],
}

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
        access = data.get("access", [])
        tool_access = {}
        for server, tools in SERVER_TOOLS.items():
            if "all" in access or server in access:
                tool_access[server] = set(tools)
            else:
                tool_access[server] = {
                    t for t in tools if f"{server}:{t}" in access
                }
        users.append({"email": doc.id, "access": access, "tool_access": tool_access})
    users.sort(key=lambda u: u["email"])
    response = templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "admin": email,
            "users": users,
            "servers": MCP_SERVERS,
            "server_tools": SERVER_TOOLS,
        },
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/login")
async def login(request: Request):
    redirect_uri = os.environ["BASE_URL"].rstrip("/") + "/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri, prompt="select_account")


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
    return RedirectResponse(url="/")


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
    tool = form.get("tool") or None
    checked = form.get("checked") == "true"

    doc_ref = db.collection(COLLECTION).document(email)
    doc = doc_ref.get()
    access = (doc.to_dict() or {}).get("access", []) if doc.exists else []

    if server == "all":
        access = ["all"] if checked else []
    elif tool:
        tools = SERVER_TOOLS.get(server, [])

        # Expand any coarser grant that currently covers this server down to
        # explicit per-tool entries, so we can flip just this one tool.
        if "all" in access:
            access = [s for s in MCP_SERVERS if s != server]
            access += [f"{server}:{t}" for t in tools]
        elif server in access:
            access = [a for a in access if a != server]
            access += [f"{server}:{t}" for t in tools]

        entry = f"{server}:{tool}"
        if checked:
            if entry not in access:
                access.append(entry)
        else:
            access = [a for a in access if a != entry]

        # Collapse back to a bare server grant if every tool ended up granted.
        granted = {a.split(":", 1)[1] for a in access if a.startswith(f"{server}:")}
        if tools and granted == set(tools):
            access = [a for a in access if not a.startswith(f"{server}:")]
            access.append(server)
    elif checked:
        access = [
            a for a in access if a != "all" and a != server and not a.startswith(f"{server}:")
        ]
        access.append(server)
    else:
        access = [a for a in access if a != server and not a.startswith(f"{server}:")]

    doc_ref.set({"access": access}, merge=True)
    return {"ok": True, "access": access}


@app.post("/users/{email}/delete")
async def delete_user(email: str, admin: str = Depends(require_admin)):
    db.collection(COLLECTION).document(email).delete()
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
