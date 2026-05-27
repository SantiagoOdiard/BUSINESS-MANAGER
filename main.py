import base64
import email
import hashlib
import hmac
import imaplib
import json
import os
import re
import secrets
import shutil
import urllib.parse
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as exc:
    raise RuntimeError("cryptography package es requerido para cifrar backups. Instala las dependencias de requirements.txt.") from exc

try:
    import pyotp
except ImportError as exc:
    pyotp = None
    pyotp_import_error = exc

from database import get_db, pwd_context, engine, create_default_admin
from models import Base, Employee, Task, User, AuditLog, Notification, SupportTicket, SupportTicketMessage, KnowledgeBaseArticle, CustomerProfile, AutomationRule, LoginAttempt, Plant, UserPlantAccess, TicketAttachment
from plant_utils import send_whatsapp_notification, export_tickets_to_excel, export_tickets_to_excel_multiple_sheets, calculate_ticket_stats, filter_tickets_by_status

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY debe configurarse en las variables de entorno y no puede ser el valor por defecto.")
serializer = URLSafeSerializer(SECRET_KEY, salt="session")
BACKUP_DIR = Path("backups")
REPORT_DIR = Path("reports")
AUTH_TOKEN_MAX_AGE = int(os.getenv("AUTH_TOKEN_MAX_AGE", "7200"))
CSRF_COOKIE_NAME = "csrf_token"
BACKUP_ENCRYPTION_KEY = os.getenv("BACKUP_ENCRYPTION_KEY")
if not BACKUP_ENCRYPTION_KEY:
    raise RuntimeError("BACKUP_ENCRYPTION_KEY debe configurarse en las variables de entorno para cifrar los backups.")
try:
    BACKUP_FERNET = Fernet(BACKUP_ENCRYPTION_KEY)
except Exception as exc:
    raise RuntimeError("BACKUP_ENCRYPTION_KEY no es un valor válido de Fernet: {}".format(exc))
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
BACKUP_MAX_FILES = int(os.getenv("BACKUP_MAX_FILES", "10"))
ENFORCE_HTTPS = os.getenv("ENFORCE_HTTPS", "true").lower() in ["1", "true", "yes"]

DEMO_LOGIN_USERNAME = "demo"
DEMO_LOGIN_PASSWORD = "Demo2026!"
DEMO_LOGIN_ROLE = "manager"


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
        request.state.csrf_token = csrf_token

        if request.method == "POST":
            # Read the request body once and store it so it can be re-read by route handlers
            body = await request.body()
            
            # Create a new receive callable that replays the body
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            
            request._receive = receive
            
            # Try to extract CSRF token from the body
            posted_token = None
            try:
                # Parse the form data to check CSRF token without consuming it permanently
                form_data = {}
                content_type = request.headers.get("content-type", "")
                if content_type.startswith("application/x-www-form-urlencoded"):
                    form_data = dict(urllib.parse.parse_qsl(body.decode(errors="ignore")))
                    posted_token = form_data.get("csrf_token")
                elif content_type.startswith("multipart/form-data"):
                    # crude multipart parsing to extract csrf_token field without heavy deps
                    try:
                        m = re.search(rb'name="csrf_token"\r\n\r\n([^\r\n]+)', body)
                        if m:
                            posted_token = m.group(1).decode(errors="ignore")
                    except Exception:
                        posted_token = None
                if not posted_token:
                    posted_token = request.headers.get("x-csrf-token")
            except Exception:
                posted_token = None
            
            if not posted_token or not hmac.compare_digest(str(posted_token), str(csrf_token)):
                return templates.TemplateResponse(
                    request,
                    "error.html",
                    {
                        "request": request,
                        "title": "Solicitud inválida",
                        "detail": "Token CSRF inválido o faltante. Vuelve a cargar el formulario e inténtalo de nuevo.",
                    },
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        response = await call_next(request)
        if request.state.csrf_token and request.cookies.get(CSRF_COOKIE_NAME) != request.state.csrf_token:
            response.set_cookie(
                CSRF_COOKIE_NAME,
                request.state.csrf_token,
                httponly=False,
                secure=True,
                samesite="strict",
                max_age=AUTH_TOKEN_MAX_AGE,
            )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=()"
        if ENFORCE_HTTPS:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response


if ENFORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(SecurityMiddleware)


@app.on_event("startup")
async def startup_event():
    """Initialize database and create default admin on startup"""
    try:
        create_default_admin()
    except Exception as e:
        print(f"⚠️  Startup error: {e}")


def create_session_token(user: User) -> str:
    return serializer.dumps({
        "user_id": user.id,
        "exp": int((datetime.utcnow() + timedelta(seconds=AUTH_TOKEN_MAX_AGE)).timestamp()),
    })


def get_current_user(request: Request, db: Session):
    session_token = request.cookies.get("session")
    if not session_token:
        return None
    try:
        payload = serializer.loads(session_token)
    except BadSignature:
        return None
    exp = payload.get("exp")
    if exp is None or datetime.utcnow().timestamp() > exp:
        return None
    return db.query(User).filter(User.id == payload.get("user_id")).first()


def require_login(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return user


def require_roles(user: User, roles: list[str]):
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos suficientes.")
    return user


def get_client_ip(request: Request) -> str:
    try:
        return request.client.host or "unknown"
    except Exception:
        return "unknown"


def is_ip_blocked(db: Session, ip_address: str) -> bool:
    window = datetime.utcnow() - timedelta(minutes=15)
    failures = db.query(LoginAttempt).filter(
        LoginAttempt.ip_address == ip_address,
        LoginAttempt.success == False,
        LoginAttempt.created_at >= window,
    ).count()
    return failures >= 10


def record_login_attempt(db: Session, username: str, ip_address: str, success: bool):
    attempt = LoginAttempt(username=username, ip_address=ip_address, success=success)
    db.add(attempt)
    db.commit()
    user = db.query(User).filter(User.username == username).first()
    if user:
        if success:
            user.failed_login_attempts = 0
            user.locked_until = None
        else:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            user.last_failed_login_at = datetime.utcnow()
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.utcnow() + timedelta(minutes=30)
        db.commit()


def validate_password_strength(password: str):
    if len(password) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña debe tener al menos 10 caracteres.")
    if not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"[0-9]", password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña debe incluir mayúsculas, minúsculas y números.")


def require_active_user(user: User):
    if user.locked_until and datetime.utcnow() < user.locked_until:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Cuenta bloqueada hasta {user.locked_until.strftime('%Y-%m-%d %H:%M')} UTC por intentos fallidos.")
    return user


def ensure_demo_user(db: Session) -> User:
    demo_user = db.query(User).filter(User.username == DEMO_LOGIN_USERNAME).first()
    if not demo_user:
        demo_user = User(
            username=DEMO_LOGIN_USERNAME,
            password_hash=pwd_context.hash(DEMO_LOGIN_PASSWORD),
            role=DEMO_LOGIN_ROLE,
        )
        db.add(demo_user)
        db.flush()

        demo_employee = Employee(
            name="Usuario Demo",
            role=DEMO_LOGIN_ROLE,
            user_id=demo_user.id,
        )
        db.add(demo_employee)
        db.flush()

        plants = db.query(Plant).all()
        for plant in plants:
            db.add(UserPlantAccess(user_id=demo_user.id, plant_id=plant.id))

        db.commit()

    else:
        plants = db.query(Plant).all()
        existing_access = {access.plant_id for access in db.query(UserPlantAccess).filter(UserPlantAccess.user_id == demo_user.id).all()}
        for plant in plants:
            if plant.id not in existing_access:
                db.add(UserPlantAccess(user_id=demo_user.id, plant_id=plant.id))
        if not demo_user.employee_profile:
            demo_employee = Employee(
                name="Usuario Demo",
                role=DEMO_LOGIN_ROLE,
                user_id=demo_user.id,
            )
            db.add(demo_employee)
        db.commit()

    if not db.query(Notification).filter(Notification.user_id == demo_user.id).first():
        db.add(Notification(user_id=demo_user.id, message="Bienvenido al demo de Business Manager. Explora tickets, tareas y reportes de ejemplo."))
        db.commit()

    return demo_user


def validate_choice(value: str | None, allowed: list[str], field_name: str):
    if value is not None and value != "" and value not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Valor inválido para {field_name}.")
    return value


def sanitize_text(value: str | None, field_name: str, max_length: int = 1024) -> str:
    if value is None:
        return ""
    text = value.strip()
    if len(text) > max_length:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} no puede exceder {max_length} caracteres.")
    return text


def encrypt_backup_payload(payload: dict) -> bytes:
    payload_bytes = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
    return BACKUP_FERNET.encrypt(payload_bytes)


def cleanup_old_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[BACKUP_MAX_FILES:]:
        old.unlink(missing_ok=True)
    expiry = datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS)
    for candidate in BACKUP_DIR.glob("*.enc"):
        if datetime.utcfromtimestamp(candidate.stat().st_mtime) < expiry:
            candidate.unlink(missing_ok=True)


def create_encrypted_backup(db: Session):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"tables": []}
    for table in Base.metadata.sorted_tables:
        rows = [dict(row) for row in db.execute(table.select()).mappings().all()]
        payload["tables"].append({
            "name": table.name,
            "columns": [column.name for column in table.columns],
            "rows": rows,
        })
    encrypted = encrypt_backup_payload(payload)
    backup_path = BACKUP_DIR / f"database_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json.enc"
    with backup_path.open("wb") as backup_file:
        backup_file.write(encrypted)
    cleanup_old_backups()
    return backup_path


def audit_log(db: Session, user: User, action: str, model_name: str, target_id=None, details=None):
    log = AuditLog(
        user_id=user.id,
        action=action,
        model_name=model_name,
        target_id=str(target_id) if target_id is not None else None,
        details=details,
        timestamp=datetime.utcnow(),
    )
    db.add(log)
    db.commit()


def notify_user(db: Session, user_id: int, message: str, employee_id: int | None = None):
    notification = Notification(user_id=user_id, employee_id=employee_id, message=message)
    db.add(notification)
    db.commit()


def get_customer_profile(db: Session, user: User) -> CustomerProfile:
    profile = db.query(CustomerProfile).filter(CustomerProfile.user_id == user.id).first()
    if not profile:
        profile = CustomerProfile(user_id=user.id, company=None, preferences=None, communication_style=None, notes=None)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def get_user_accessible_plant_ids(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        return [plant.id for plant in db.query(Plant).all()]
    return [access.plant_id for access in db.query(UserPlantAccess).filter(UserPlantAccess.user_id == user.id).all()]


def add_profile_memory(db: Session, profile: CustomerProfile, message: str, answer: str):
    existing = profile.notes or ""
    entries = [line for line in existing.splitlines() if line.strip()]
    entry = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] Q: {message.strip()} | A: {answer.strip()}"
    entries.append(entry)
    profile.notes = "\n".join(entries[-12:])
    profile.updated_at = datetime.utcnow()
    db.commit()


def find_relevant_articles(articles: list[KnowledgeBaseArticle], query: str) -> list[KnowledgeBaseArticle]:
    value = query.strip().lower()
    if not value:
        return []
    results = []
    for article in articles:
        if value in article.title.lower() or value in article.content.lower() or value in article.category.lower():
            results.append(article)
    return results[:5]


def find_profile_memory(profile: CustomerProfile, query: str) -> str | None:
    if not profile or not profile.notes:
        return None
    lines = [line for line in (profile.notes or "").splitlines() if line.strip()]
    query_lower = query.strip().lower()
    relevant = [line for line in lines if query_lower in line.lower()]
    return relevant[-1] if relevant else None


def match_automation_rule(ticket: SupportTicket, rule: AutomationRule) -> bool:
    value = rule.condition_value.strip().lower()
    if rule.condition_type == "subject_contains":
        return value in ticket.subject.lower()
    if rule.condition_type == "description_contains":
        return value in ticket.description.lower()
    if rule.condition_type == "channel_equals":
        return value == ticket.channel.lower()
    if rule.condition_type == "priority_equals":
        return value == ticket.priority.lower()
    if rule.condition_type == "status_equals":
        return value == ticket.status.lower()
    return False


def apply_ticket_automation(db: Session, ticket: SupportTicket):
    rules = db.query(AutomationRule).filter(AutomationRule.active == True).all()
    for rule in rules:
        if match_automation_rule(ticket, rule):
            applied = False
            if rule.action_assign_to:
                assignee = db.query(Employee).filter(Employee.id == rule.action_assign_to).first()
                if assignee:
                    ticket.assigned_to = assignee.id
                    if assignee.account:
                        notify_user(db, assignee.account.id, f"Nuevo ticket asignado por regla: {ticket.subject}", employee_id=assignee.id)
                    applied = True
            if rule.action_set_priority:
                ticket.priority = rule.action_set_priority
                applied = True
            if rule.action_set_status:
                ticket.status = rule.action_set_status
                applied = True
            if applied:
                ticket.last_updated = datetime.utcnow()
                db.commit()
                db.refresh(ticket)
                db.add(SupportTicketMessage(
                    ticket_id=ticket.id,
                    sender_type="system",
                    sender_name="Automatización",
                    content=f"Regla aplicada: {rule.name}.",
                ))
                db.commit()
                return

    subject = ticket.subject.lower()
    description = ticket.description.lower()
    if "reembolso" in subject or "reembolso" in description or "refund" in subject:
        finance = db.query(Employee).filter(Employee.role.ilike("%finanzas%") | Employee.role.ilike("%finance%"))
        assignee = finance.first()
        if assignee:
            ticket.assigned_to = assignee.id
            ticket.status = ticket.status or "pending"
            ticket.last_updated = datetime.utcnow()
            db.commit()
            db.refresh(ticket)
            db.add(SupportTicketMessage(
                ticket_id=ticket.id,
                sender_type="system",
                sender_name="Automatización",
                content=f"Ticket enroutado a finanzas según el asunto: {ticket.subject}",
            ))
            db.commit()
            if assignee.account:
                notify_user(db, assignee.account.id, f"Nuevo ticket urgente asignado a finanzas: {ticket.subject}", employee_id=assignee.id)
            return
    if ticket.priority == "urgent" or "urgente" in subject or "urgente" in description:
        manager = db.query(Employee).filter(Employee.role.ilike("%manager%") | Employee.role.ilike("%gerente%"))
        assignee = manager.first()
        if assignee:
            ticket.assigned_to = assignee.id
            ticket.status = ticket.status or "pending"
            ticket.last_updated = datetime.utcnow()
            db.commit()
            db.refresh(ticket)
            db.add(SupportTicketMessage(
                ticket_id=ticket.id,
                sender_type="system",
                sender_name="Automatización",
                content=f"Ticket urgente escalado automáticamente al agente {assignee.name}.",
            ))
            db.commit()
            if assignee.account:
                notify_user(db, assignee.account.id, f"Un ticket urgente ha sido asignado a ti: {ticket.subject}", employee_id=assignee.id)
            return


def generate_support_report(db: Session):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    users = db.query(User).order_by(User.id).all()
    employees = db.query(Employee).order_by(Employee.id).all()
    tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).all()
    status_counts = {
        "open": sum(1 for t in tickets if t.status == "open"),
        "pending": sum(1 for t in tickets if t.status == "pending"),
        "in_progress": sum(1 for t in tickets if t.status == "in_progress"),
        "closed": sum(1 for t in tickets if t.status == "closed"),
    }
    total_tickets = len(tickets)
    report_path = REPORT_DIR / "support_report.md"
    with report_path.open("w", encoding="utf-8") as report_file:
        report_file.write("# Informe de Soporte Empresarial\n\n")
        report_file.write("**Business Manager - Sistema de Gestión Empresarial**\n\n")
        report_file.write(f"**Generado el:** {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S')} UTC\n\n")
        report_file.write("---\n\n")
        report_file.write("## Resumen Ejecutivo\n\n")
        report_file.write("Este informe proporciona una visión completa del estado actual del sistema de soporte técnico, incluyendo estadísticas de tickets, usuarios registrados y empleados activos.\n\n")
        report_file.write("### Estadísticas Generales de Tickets\n\n")
        report_file.write(f"- **Total de tickets registrados:** {total_tickets}\n")
        report_file.write(f"- **Tickets abiertos:** {status_counts['open']}\n")
        report_file.write(f"- **Tickets pendientes:** {status_counts['pending']}\n")
        report_file.write(f"- **Tickets en progreso:** {status_counts['in_progress']}\n")
        report_file.write(f"- **Tickets cerrados:** {status_counts['closed']}\n\n")
        if total_tickets > 0:
            open_percentage = (status_counts['open'] / total_tickets) * 100
            closed_percentage = (status_counts['closed'] / total_tickets) * 100
            report_file.write(f"- **Porcentaje de tickets abiertos:** {open_percentage:.1f}%\n")
            report_file.write(f"- **Porcentaje de tickets cerrados:** {closed_percentage:.1f}%\n\n")
        report_file.write("---\n\n")
        report_file.write("## Detalle de Tickets Registrados\n\n")
        report_file.write("A continuación se detalla cada ticket registrado en el sistema, ordenados por fecha de creación (más recientes primero).\n\n")
        if tickets:
            report_file.write("| ID | Cliente | Canal | Asunto | Prioridad | Estado | Asignado a | Creado por | Fecha de Creación | Última Actualización |\n")
            report_file.write("|----|--------|-------|--------|-----------|--------|------------|------------|-------------------|---------------------|\n")
            for ticket in tickets:
                assigned_name = ticket.assigned_employee.name if ticket.assigned_employee else "Sin asignar"
                report_file.write(
                    f"| {ticket.id} | {ticket.user.username} | {ticket.channel} | {ticket.subject} | {ticket.priority.capitalize()} | {ticket.status.replace('_', ' ').capitalize()} | {assigned_name} | {ticket.user.username} | {ticket.created_at.strftime('%d/%m/%Y %H:%M')} | {ticket.last_updated.strftime('%d/%m/%Y %H:%M')} |\n"
                )
        else:
            report_file.write("*No hay tickets registrados en el sistema.*\n\n")
        report_file.write("\n---\n\n")
        report_file.write("## Usuarios del Sistema\n\n")
        report_file.write("Lista completa de usuarios registrados, incluyendo su rol y fecha de creación.\n\n")
        report_file.write("| ID | Nombre de Usuario | Rol | Fecha de Registro |\n")
        report_file.write("|----|-------------------|-----|-------------------|\n")
        for user in users:
            report_file.write(f"| {user.id} | {user.username} | {user.role.capitalize()} | {user.created_at.strftime('%d/%m/%Y %H:%M')} |\n")
        report_file.write("\n---\n\n")
        report_file.write("## Empleados Registrados\n\n")
        report_file.write("Información de los empleados activos en el sistema, incluyendo su rol y asociación con usuarios.\n\n")
        report_file.write("| ID | Nombre Completo | Rol | Usuario Asociado | Fecha de Registro |\n")
        report_file.write("|----|-----------------|-----|------------------|-------------------|\n")
        for employee in employees:
            account_username = employee.account.username if employee.account else "No definido"
            report_file.write(
                f"| {employee.id} | {employee.name} | {employee.role} | {account_username} | {employee.created_at.strftime('%d/%m/%Y %H:%M')} |\n"
            )
        report_file.write("\n---\n\n")
        report_file.write("## Notas Adicionales\n\n")
        report_file.write("- Este informe se genera automáticamente cada vez que se realiza un cambio en los tickets.\n")
        report_file.write("- Para acceder al sistema completo, visite la plataforma web en la URL configurada.\n")
        report_file.write("- Contacte al administrador del sistema para cualquier consulta técnica.\n\n")
        report_file.write("**Fin del Informe**\n")


def decode_email_header(value: str) -> str:
    if not value:
        return ""
    decoded_fragments = decode_header(value)
    parts = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            try:
                parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
            except LookupError:
                parts.append(fragment.decode("utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts).strip()


def parse_email_message(raw_message: bytes):
    message = email.message_from_bytes(raw_message)
    subject = decode_email_header(message.get("Subject", "Sin asunto"))
    from_name, from_addr = parseaddr(message.get("From", ""))
    body = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
    else:
        charset = message.get_content_charset() or "utf-8"
        body = message.get_payload(decode=True).decode(charset, errors="replace")

    message_id = message.get("Message-ID")
    received_at = None
    try:
        date_header = message.get("Date")
        if date_header:
            received_at = parsedate_to_datetime(date_header)
    except Exception:
        received_at = None

    return subject, from_name or from_addr, from_addr, body.strip(), message_id, received_at


def log_ticket_message(db: Session, ticket_id: int, sender_type: str, sender_name: str, content: str):
    message = SupportTicketMessage(
        ticket_id=ticket_id,
        sender_type=sender_type,
        sender_name=sender_name,
        content=content.strip(),
        internal=False,
    )
    db.add(message)
    db.commit()


def get_email_import_user(db: Session) -> User:
    username = os.getenv("EMAIL_IMPORT_USER", "email_import")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            password_hash=pwd_context.hash(os.getenv("EMAIL_IMPORT_PASSWORD", "email_import_secret")),
            role="staff",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def import_emails_from_inbox(db: Session, limit: int = 20, mark_seen: bool = True):
    host = os.getenv("EMAIL_IMAP_HOST")
    username = os.getenv("EMAIL_IMAP_USERNAME")
    password = os.getenv("EMAIL_IMAP_PASSWORD")
    folder = os.getenv("EMAIL_IMAP_FOLDER", "INBOX")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))

    imported_ticket_ids = []
    import_errors = []

    if not host or not username or not password:
        import_errors.append("Faltan las variables de entorno EMAIL_IMAP_HOST, EMAIL_IMAP_USERNAME o EMAIL_IMAP_PASSWORD.")
        return imported_ticket_ids, import_errors

    try:
        connection = imaplib.IMAP4_SSL(host, port)
        connection.login(username, password)
        connection.select(folder)
        status, data = connection.search(None, "UNSEEN" if mark_seen else "ALL")
        if status != "OK":
            import_errors.append("No se pudo buscar mensajes en la bandeja de entrada.")
            connection.logout()
            return imported_ticket_ids, import_errors

        message_ids = data[0].split()[-limit:]
        support_user = get_email_import_user(db)

        for msg_id in message_ids:
            status, fetch_data = connection.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetch_data or not fetch_data[0]:
                import_errors.append(f"No se pudo descargar el mensaje {msg_id.decode()}.")
                continue
            raw = fetch_data[0][1]
            if not raw:
                import_errors.append(f"Mensaje {msg_id.decode()} vacío.")
                continue

            subject, sender_name, sender_address, body, message_id, received_at = parse_email_message(raw)
            ticket = SupportTicket(
                user_id=support_user.id,
                subject=subject or "Correo sin asunto",
                description=body or "(Sin cuerpo de texto)",
                channel="email",
                priority="urgent" if "urgent" in subject.lower() or "urgente" in subject.lower() else "normal",
                status="open",
                email_from=sender_address,
                email_message_id=message_id,
                received_at=received_at or datetime.utcnow(),
                last_updated=datetime.utcnow(),
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            log_ticket_message(db, ticket.id, "customer", sender_name or sender_address, body or "(Mensaje en blanco)")
            apply_ticket_automation(db, ticket)
            imported_ticket_ids.append(ticket.id)
            if mark_seen:
                connection.store(msg_id, "+FLAGS", "\\Seen")

        connection.logout()
    except Exception as exc:
        import_errors.append(str(exc))

    return imported_ticket_ids, import_errors


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"request": request, "title": f"Error {exc.status_code}", "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"request": request, "title": "Error interno", "detail": str(exc)},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"request": request})


@app.get("/login/demo")
def login_demo(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse(url="/plants", status_code=status.HTTP_303_SEE_OTHER)

    demo_user = ensure_demo_user(db)
    record_login_attempt(db, DEMO_LOGIN_USERNAME, get_client_ip(request), True)
    response = RedirectResponse(url="/plants", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "session",
        create_session_token(demo_user),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=AUTH_TOKEN_MAX_AGE,
    )
    return response


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), mfa_token: str | None = Form(None), db: Session = Depends(get_db)):
    username_value = sanitize_text(username, "Usuario", max_length=64).lower()
    client_ip = get_client_ip(request)
    if is_ip_blocked(db, client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Demasiados intentos fallidos desde esta IP. Intenta de nuevo más tarde.")
    user = db.query(User).filter(User.username == username_value).first()

    if not user or not pwd_context.verify(password, user.password_hash):
        record_login_attempt(db, username_value, client_ip, False)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "Usuario o contraseña incorrectos."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    require_active_user(user)

    if user.mfa_enabled:
        if pyotp is None:
            raise RuntimeError("pyotp es requerido para MFA. Instala las dependencias de requirements.txt.")
        if not mfa_token or not user.mfa_secret:
            record_login_attempt(db, username_value, client_ip, False)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"request": request, "error": "Se requiere el código MFA para iniciar sesión."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(mfa_token.strip(), valid_window=1):
            record_login_attempt(db, username_value, client_ip, False)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"request": request, "error": "Código MFA incorrecto."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    record_login_attempt(db, username_value, client_ip, True)
    response = RedirectResponse(url="/plants", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "session",
        create_session_token(user),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=AUTH_TOKEN_MAX_AGE,
    )
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session")
    return response


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    return RedirectResponse(url="/plants", status_code=status.HTTP_303_SEE_OTHER)
    tasks = db.query(Task).all()
    tickets = db.query(SupportTicket).all()
    users = db.query(User).all()
    available_users = [user for user in users if not user.employee_profile]
    assignable_employees = [emp for emp in employees if emp.user_id]
    notifications = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.read == False).all()
    total_tasks = len(tasks)
    pending_tasks = len([task for task in tasks if task.status == "pending"])
    total_employees = len(employees)
    total_tickets = len(tickets)
    open_tickets = len([ticket for ticket in tickets if ticket.status in ["open", "pending", "in_progress"]])
    urgent_tickets = len([ticket for ticket in tickets if ticket.priority == "urgent"])

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "current_user": current_user,
            "employees": employees,
            "tasks": tasks,
            "tickets": tickets,
            "available_users": available_users,
            "assignable_employees": assignable_employees,
            "notifications": notifications,
            "total_tasks": total_tasks,
            "pending_tasks": pending_tasks,
            "total_employees": total_employees,
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "urgent_tickets": urgent_tickets,
        },
    )


@app.post("/employees")
def create_employee(
    request: Request,
    user_id: int = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado para crear empleado.")
    if user.employee_profile:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este usuario ya está asociado a un empleado.")

    role_value = sanitize_text(role, "Rol del empleado", max_length=64)
    employee = Employee(name=user.username, role=role_value, user_id=user.id)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    audit_log(db, current_user, "create", "Employee", target_id=employee.id, details=f"Empleado {employee.name} creado y vinculado al usuario {user.username}")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    priority: str = Form(...),
    status: str = Form(...),
    assigned_to: int = Form(...),
    plant_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user

    title_value = sanitize_text(title, "Título de la tarea", max_length=128)
    description_value = sanitize_text(description, "Descripción de la tarea", max_length=2048)
    validate_choice(priority, ["low", "medium", "normal", "high", "urgent"], "prioridad")
    validate_choice(status, ["pending", "in_progress", "completed", "open", "closed"], "estado")

    if plant_id is None:
        default_plant = db.query(Plant).first()
        plant_id = default_plant.id if default_plant else 1
    else:
        plant = db.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada para la tarea.")

    if current_user.role != "admin":
        access = db.query(UserPlantAccess).filter(
            UserPlantAccess.user_id == current_user.id,
            UserPlantAccess.plant_id == plant_id,
        ).first()
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso para crear tareas en esta planta.")

    task = Task(
        title=title_value,
        description=description_value,
        priority=priority,
        status=status,
        assigned_to=assigned_to,
        plant_id=plant_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if task.employee and task.employee.account:
        notify_user(db, task.employee.account.id, f"Nueva tarea asignada: {task.title}", employee_id=task.employee.id)
    audit_log(db, current_user, "create", "Task", target_id=task.id, details=f"Tarea {task.title} creada")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/tasks/{task_id}/complete")
def complete_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada.")
    task.status = "completed"
    db.commit()
    if task.employee and task.employee.account:
        notify_user(db, task.employee.account.id, f"La tarea '{task.title}' ha sido completada.", employee_id=task.employee.id)
    audit_log(db, current_user, "update", "Task", target_id=task.id, details=f"Tarea {task.title} marcada como completada")
    return RedirectResponse(url="/tasks", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/tasks", response_class=HTMLResponse)
def read_tasks(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "25"))
    query = db.query(Task).order_by(Task.created_at.desc())
    if current_user.role != "admin":
        plant_ids = get_user_accessible_plant_ids(db, current_user)
        if plant_ids:
            query = query.filter(Task.plant_id.in_(plant_ids))
        else:
            return templates.TemplateResponse(request, "tasks.html", {"request": request, "current_user": current_user, "tasks": [], "plant": None})
    total = query.count()
    tasks = query.offset((page - 1) * page_size).limit(page_size).all()
    return templates.TemplateResponse(request, "tasks.html", {"request": request, "current_user": current_user, "tasks": tasks, "plant": None, "total": total, "page": page, "page_size": page_size})


@app.get("/tasks/export_csv")
def export_tasks_csv(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    query = db.query(Task)
    if current_user.role != "admin":
        plant_ids = get_user_accessible_plant_ids(db, current_user)
        if plant_ids:
            query = query.filter(Task.plant_id.in_(plant_ids))
        else:
            query = query.filter(False)
    tasks = query.order_by(Task.created_at.desc()).all()
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","title","description","priority","status","assigned_to","plant","created_at"])
    for t in tasks:
        writer.writerow([
            t.id,
            t.title,
            (t.description or "").replace('\n',' '),
            t.priority,
            t.status,
            (t.employee.name if t.employee else ""),
            (t.plant.name if t.plant else ""),
            t.created_at.isoformat() if t.created_at else "",
        ])
    csv_data = output.getvalue()
    return Response(content=csv_data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tasks.csv"})


@app.get("/plant/{plant_id}/tasks", response_class=HTMLResponse)
def view_plant_tasks(request: Request, plant_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user

    access = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id,
        UserPlantAccess.plant_id == plant_id
    ).first()
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta planta.")

    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada.")

    tasks = db.query(Task).filter(Task.plant_id == plant_id).all()
    return templates.TemplateResponse(request, "tasks.html", {"request": request, "current_user": current_user, "tasks": tasks, "plant": plant})


@app.get("/notifications", response_class=HTMLResponse)
def read_notifications(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    notifications = db.query(Notification).filter(Notification.user_id == current_user.id).order_by(Notification.created_at.desc()).all()
    return templates.TemplateResponse(request, "notifications.html", {"request": request, "current_user": current_user, "notifications": notifications})


@app.get("/notifications/count")
def notifications_count(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return JSONResponse({"count": 0})
    count = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.read == False).count()
    return JSONResponse({"count": count})


@app.post("/notifications/mark_all_read")
def notifications_mark_all_read(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    db.query(Notification).filter(Notification.user_id == current_user.id, Notification.read == False).update({"read": True})
    db.commit()
    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/notifications/{notification_id}/read")
def mark_notification_read(request: Request, notification_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificación no encontrada.")
    notification.read = True
    db.commit()
    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/assistant", response_class=HTMLResponse)
def assistant_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    profile = get_customer_profile(db, current_user)
    return templates.TemplateResponse(request, "assistant.html", {"request": request, "current_user": current_user, "profile": profile})


@app.post("/assistant", response_class=HTMLResponse)
def assistant_submit(request: Request, message: str = Form(...), db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    profile = get_customer_profile(db, current_user)
    articles = db.query(KnowledgeBaseArticle).order_by(KnowledgeBaseArticle.created_at.desc()).all()
    answer = generate_ai_response(message, profile, articles)
    add_profile_memory(db, profile, message, answer)
    return templates.TemplateResponse(
        request,
        "assistant.html",
        {
            "request": request,
            "current_user": current_user,
            "user_message": message,
            "assistant_answer": answer,
            "profile": profile,
            "relevant_articles": find_relevant_articles(articles, message),
        },
    )


@app.get("/profile", response_class=HTMLResponse)
def profile_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    profile = get_customer_profile(db, current_user)
    return templates.TemplateResponse(request, "customer_profile.html", {"request": request, "current_user": current_user, "profile": profile})


@app.post("/profile", response_class=HTMLResponse)
def profile_update(request: Request,
    company: str = Form(""),
    communication_style: str = Form(""),
    preferences: str = Form(""),
    notes: str = Form(""),
    mfa_action: str = Form(""),
    mfa_token: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    profile = get_customer_profile(db, current_user)
    profile.company = sanitize_text(company, "Compañía", max_length=128) or profile.company
    profile.communication_style = sanitize_text(communication_style, "Estilo de comunicación", max_length=32) or profile.communication_style
    profile.preferences = sanitize_text(preferences, "Preferencias", max_length=2048) or profile.preferences
    profile.notes = sanitize_text(notes, "Notas", max_length=2048) or profile.notes

    if mfa_action == "generate":
        if pyotp is None:
            raise RuntimeError("pyotp es requerido para MFA. Instala las dependencias de requirements.txt.")
        current_user.mfa_secret = pyotp.random_base32()
        current_user.mfa_enabled = False
        db.commit()
        return templates.TemplateResponse(request, "customer_profile.html", {
            "request": request,
            "current_user": current_user,
            "profile": profile,
            "mfa_secret": current_user.mfa_secret,
            "mfa_message": "Escanea esta clave en tu app de autenticación y confirma con un código TOTP.",
        })
    if mfa_action == "verify":
        if pyotp is None:
            raise RuntimeError("pyotp es requerido para MFA. Instala las dependencias de requirements.txt.")
        if not current_user.mfa_secret:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se ha generado una clave MFA.")
        totp = pyotp.TOTP(current_user.mfa_secret)
        if not mfa_token or not totp.verify(mfa_token.strip(), valid_window=1):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código MFA incorrecto.")
        current_user.mfa_enabled = True
    if mfa_action == "disable":
        current_user.mfa_enabled = False
        current_user.mfa_secret = None

    profile.updated_at = datetime.utcnow()
    db.commit()
    audit_log(db, current_user, "update", "CustomerProfile", target_id=profile.id, details="Perfil de cliente actualizado")
    return RedirectResponse(url="/profile", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/support", response_class=HTMLResponse)
def support_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    # Filters and pagination
    q = request.query_params.get("q", "").strip()
    plant = request.query_params.get("plant")
    status = request.query_params.get("status")
    priority = request.query_params.get("priority")
    assigned_to = request.query_params.get("assigned_to")
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "25"))

    ticket_scope = db.query(SupportTicket)
    if current_user.role not in ['admin', 'manager', 'supervisor']:
        ticket_scope = ticket_scope.filter(
            (SupportTicket.user_id == current_user.id)
            | (SupportTicket.assigned_to == (current_user.employee_profile.id if current_user.employee_profile else None))
        )

    if current_user.role != 'admin':
        accessible = get_user_accessible_plant_ids(db, current_user)
        ticket_scope = ticket_scope.filter(SupportTicket.plant_id.in_(accessible))

    stats = {
        "open": ticket_scope.filter(SupportTicket.status == "open").count(),
        "pending": ticket_scope.filter(SupportTicket.status == "pending").count(),
        "in_progress": ticket_scope.filter(SupportTicket.status == "in_progress").count(),
        "closed": ticket_scope.filter(SupportTicket.status == "closed").count(),
        "automation_rules": db.query(AutomationRule).filter(AutomationRule.active == True).count(),
        "overdue": ticket_scope.filter(SupportTicket.sla_due != None, SupportTicket.sla_due < datetime.utcnow(), SupportTicket.status != 'closed').count(),
    }

    tickets_query = ticket_scope
    if q:
        like = f"%{q}%"
        tickets_query = tickets_query.filter((SupportTicket.subject.ilike(like)) | (SupportTicket.description.ilike(like)))
    if plant:
        tickets_query = tickets_query.filter(SupportTicket.plant_id == int(plant))
    if status:
        tickets_query = tickets_query.filter(SupportTicket.status == status)
    if priority:
        tickets_query = tickets_query.filter(SupportTicket.priority == priority)
    if assigned_to:
        tickets_query = tickets_query.filter(SupportTicket.assigned_to == int(assigned_to))

    total = tickets_query.count()
    tickets = tickets_query.order_by(SupportTicket.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    plants = db.query(Plant).all()
    agents = db.query(Employee).filter(Employee.user_id.isnot(None)).all()

    return templates.TemplateResponse(
        request,
        "support.html",
        {
            "request": request,
            "current_user": current_user,
            "tickets": tickets,
            "stats": stats,
            "imported_messages": [],
            "import_errors": [],
            "plants": plants,
            "agents": agents,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@app.get("/support/export_csv")
def export_support_csv(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    # reuse filter logic from support_form
    q = request.query_params.get("q", "").strip()
    plant = request.query_params.get("plant")
    status = request.query_params.get("status")
    priority = request.query_params.get("priority")
    assigned_to = request.query_params.get("assigned_to")

    ticket_scope = db.query(SupportTicket)
    if current_user.role not in ['admin', 'manager', 'supervisor']:
        ticket_scope = ticket_scope.filter(
            (SupportTicket.user_id == current_user.id)
            | (SupportTicket.assigned_to == (current_user.employee_profile.id if current_user.employee_profile else None))
        )
    if current_user.role != 'admin':
        accessible = get_user_accessible_plant_ids(db, current_user)
        ticket_scope = ticket_scope.filter(SupportTicket.plant_id.in_(accessible))
    if q:
        like = f"%{q}%"
        ticket_scope = ticket_scope.filter((SupportTicket.subject.ilike(like)) | (SupportTicket.description.ilike(like)))
    if plant:
        ticket_scope = ticket_scope.filter(SupportTicket.plant_id == int(plant))
    if status:
        ticket_scope = ticket_scope.filter(SupportTicket.status == status)
    if priority:
        ticket_scope = ticket_scope.filter(SupportTicket.priority == priority)
    if assigned_to:
        ticket_scope = ticket_scope.filter(SupportTicket.assigned_to == int(assigned_to))

    tickets = ticket_scope.order_by(SupportTicket.created_at.desc()).all()

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","user","plant","channel","subject","priority","status","assigned_to","created_at","last_updated","sla_due"])
    for t in tickets:
        writer.writerow([
            t.id,
            t.user.username if t.user else "",
            t.plant.name if t.plant else "",
            t.channel,
            t.subject,
            t.priority,
            t.status,
            (t.assigned_employee.name if t.assigned_employee else ""),
            t.created_at.isoformat() if t.created_at else "",
            t.last_updated.isoformat() if t.last_updated else "",
            t.sla_due.isoformat() if t.sla_due else "",
        ])
    csv_data = output.getvalue()
    return Response(content=csv_data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=support_tickets.csv"})


@app.get("/support/automation-rules", response_class=HTMLResponse)
def automation_rules_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    rules = db.query(AutomationRule).order_by(AutomationRule.name.asc()).all()
    return templates.TemplateResponse(
        request,
        "automation_rules.html",
        {
            "request": request,
            "current_user": current_user,
            "rules": rules,
        },
    )


@app.post("/support/automation-rules", response_class=HTMLResponse)
def automation_rules_create(
    request: Request,
    name: str = Form(...),
    condition_type: str = Form(...),
    condition_value: str = Form(...),
    action_assign_to: int | None = Form(None),
    action_set_priority: str | None = Form(None),
    action_set_status: str | None = Form(None),
    active: str | None = Form(None),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    name_value = sanitize_text(name, "Nombre de regla", max_length=128)
    condition_value_clean = sanitize_text(condition_value, "Valor de condición", max_length=256)
    validate_choice(condition_type, ["subject_contains", "description_contains", "channel_equals", "priority_equals", "status_equals"], "tipo de condición")
    validate_choice(action_set_priority, ["", "normal", "high", "urgent"], "prioridad de acción")
    validate_choice(action_set_status, ["", "open", "pending", "in_progress", "closed"], "estado de acción")
    rule = AutomationRule(
        name=name_value,
        condition_type=condition_type,
        condition_value=condition_value_clean,
        action_assign_to=action_assign_to,
        action_set_priority=action_set_priority or None,
        action_set_status=action_set_status or None,
        active=active is not None,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    audit_log(db, current_user, "create", "AutomationRule", target_id=rule.id, details=f"Regla creada: {rule.name}")
    return RedirectResponse(url="/support/automation-rules", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/support/automation-rules/{rule_id}/edit", response_class=HTMLResponse)
def automation_rule_edit(request: Request, rule_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    return templates.TemplateResponse(request, "automation_rule_edit.html", {"request": request, "current_user": current_user, "rule": rule})


@app.post("/support/automation-rules/{rule_id}/edit", response_class=HTMLResponse)
def automation_rule_update(
    request: Request,
    rule_id: int,
    name: str = Form(...),
    condition_type: str = Form(...),
    condition_value: str = Form(...),
    action_assign_to: int | None = Form(None),
    action_set_priority: str | None = Form(None),
    action_set_status: str | None = Form(None),
    active: str | None = Form(None),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    rule.name = sanitize_text(name, "Nombre de regla", max_length=128)
    validate_choice(condition_type, ["subject_contains", "description_contains", "channel_equals", "priority_equals", "status_equals"], "tipo de condición")
    rule.condition_type = condition_type
    rule.condition_value = sanitize_text(condition_value, "Valor de condición", max_length=256)
    rule.action_assign_to = action_assign_to
    rule.action_set_priority = action_set_priority or None
    rule.action_set_status = action_set_status or None
    rule.active = active is not None
    db.commit()
    audit_log(db, current_user, "update", "AutomationRule", target_id=rule.id, details=f"Regla actualizada: {rule.name}")
    return RedirectResponse(url="/support/automation-rules", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/support/automation-rules/{rule_id}/delete")
def automation_rule_delete(request: Request, rule_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada.")
    db.delete(rule)
    db.commit()
    audit_log(db, current_user, "delete", "AutomationRule", target_id=rule_id, details=f"Regla eliminada: {rule.name}")
    return RedirectResponse(url="/support/automation-rules", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/support/import-emails", response_class=HTMLResponse)
def support_import_emails(request: Request, db: Session = Depends(get_db), limit: int = 20, search: str = ""):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    imported_messages, import_errors = import_emails_from_inbox(db, limit=limit)
    ticket_scope = db.query(SupportTicket)
    stats = {
        "open": ticket_scope.filter(SupportTicket.status == "open").count(),
        "pending": ticket_scope.filter(SupportTicket.status == "pending").count(),
        "in_progress": ticket_scope.filter(SupportTicket.status == "in_progress").count(),
        "closed": ticket_scope.filter(SupportTicket.status == "closed").count(),
    }
    tickets_query = ticket_scope
    if search:
        tickets_query = tickets_query.filter(SupportTicket.subject.ilike(f"%{search}%"))
    tickets = tickets_query.order_by(SupportTicket.created_at.desc()).all()
    generate_support_report(db)
    return templates.TemplateResponse(
        request,
        "support.html",
        {
            "request": request,
            "current_user": current_user,
            "tickets": tickets,
            "stats": stats,
            "imported_messages": imported_messages,
            "import_errors": import_errors,
        },
    )



@app.post("/support", response_class=HTMLResponse)
def support_submit(
    request: Request,
    subject: str = Form(...),
    description: str = Form(...),
    channel: str = Form("email"),
    priority: str = Form("normal"),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user

    subject_value = sanitize_text(subject, "Asunto", max_length=128)
    description_value = sanitize_text(description, "Descripción", max_length=4096)
    validate_choice(channel, ["web", "email", "chat", "phone"], "canal")
    validate_choice(priority, ["normal", "high", "urgent"], "prioridad")

    ticket = SupportTicket(
        user_id=current_user.id,
        subject=subject_value,
        description=description_value,
        channel=channel,
        priority=priority,
        status="open",
        last_updated=datetime.utcnow(),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    log_ticket_message(db, ticket.id, "customer", current_user.username, f"Ticket abierto vía {channel}. {description_value}")
    apply_ticket_automation(db, ticket)
    generate_support_report(db)
    audit_log(db, current_user, "create", "SupportTicket", target_id=ticket.id, details=f"Ticket creado: {ticket.subject}")
    return RedirectResponse(url="/support", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/support/ticket/{ticket_id}", response_class=HTMLResponse)
def read_support_ticket(request: Request, ticket_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado.")
    allowed_employee_id = current_user.employee_profile.id if current_user.employee_profile else None
    if current_user.role not in ["admin", "manager"] and ticket.user_id != current_user.id and ticket.assigned_to != allowed_employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este ticket.")
    messages = db.query(SupportTicketMessage).filter(SupportTicketMessage.ticket_id == ticket.id).order_by(SupportTicketMessage.created_at.asc()).all()
    assignee = ticket.assigned_employee if ticket.assigned_to else None
    agents = db.query(Employee).filter(Employee.user_id.isnot(None)).all()
    return templates.TemplateResponse(
        request,
        "support_ticket.html",
        {
            "request": request,
            "current_user": current_user,
            "ticket": ticket,
            "messages": messages,
            "assignee": assignee,
            "agents": agents,
        },
    )


@app.post("/support/ticket/{ticket_id}/reply")
def reply_support_ticket(
    request: Request,
    ticket_id: int,
    message: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado.")
    allowed_employee_id = current_user.employee_profile.id if current_user.employee_profile else None
    if current_user.role in ["staff"] and ticket.assigned_to != allowed_employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes responder este ticket.")
    if current_user.role not in ["admin", "manager", "staff"] and ticket.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes responder este ticket.")
    message_value = sanitize_text(message, "Mensaje", max_length=4096)
    sender_type = "agent" if current_user.role in ["admin", "manager", "staff"] else "customer"
    log_ticket_message(db, ticket.id, sender_type, current_user.username, message_value)
    ticket.last_updated = datetime.utcnow()
    ticket.status = ticket.status if ticket.status != "closed" else "open"
    db.commit()
    generate_support_report(db)
    if ticket.assigned_employee and ticket.assigned_employee.account:
        notify_user(db, ticket.assigned_employee.account.id, f"Nuevo mensaje en el ticket #{ticket.id}: {ticket.subject}", employee_id=ticket.assigned_employee.id)
    return RedirectResponse(url=f"/support/ticket/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/support/ticket/{ticket_id}/update")
def update_support_ticket(
    request: Request,
    ticket_id: int,
    status: str = Form(...),
    priority: str = Form(...),
    assigned_to: int | None = Form(None),
    sla_due: str | None = Form(None),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado.")

    allowed_employee_id = current_user.employee_profile.id if current_user.employee_profile else None
    is_assignee = current_user.role == "staff" and ticket.assigned_to == allowed_employee_id
    is_admin_manager = current_user.role in ["admin", "manager", "supervisor"]

    if not (is_admin_manager or is_assignee):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para actualizar este ticket.")

    validate_choice(status, ["open", "pending", "in_progress", "closed"], "estado")
    ticket.status = status
    ticket.last_updated = datetime.utcnow()

    if is_admin_manager:
        validate_choice(priority, ["normal", "high", "urgent"], "prioridad")
        ticket.priority = priority
        ticket.assigned_to = assigned_to
        if sla_due:
            try:
                # supports 'YYYY-MM-DDTHH:MM' or ISO formats
                parsed = datetime.fromisoformat(sla_due)
                ticket.sla_due = parsed
            except Exception:
                # ignore invalid formats
                pass
    
    db.commit()
    if ticket.status != "closed":
        apply_ticket_automation(db, ticket)
    generate_support_report(db)
    log_ticket_message(db, ticket.id, "system", "Automatización", f"Ticket actualizado: estado={status}, prioridad={ticket.priority}, asignado a {ticket.assigned_to or 'ninguno'}.")
    audit_log(db, current_user, "update", "SupportTicket", target_id=ticket.id, details=f"Ticket actualizado por {current_user.username}")
    return RedirectResponse(url=f"/support/ticket/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/support/ticket/{ticket_id}/quick-update")
def quick_update_support_ticket(
    request: Request,
    ticket_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado.")

    allowed_employee_id = current_user.employee_profile.id if current_user.employee_profile else None
    is_assignee = current_user.role == "staff" and ticket.assigned_to == allowed_employee_id
    is_admin_manager = current_user.role in ["admin", "manager", "supervisor"]

    if not (is_admin_manager or is_assignee):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para actualizar este ticket.")

    ticket.status = status
    ticket.last_updated = datetime.utcnow()
    db.commit()
    generate_support_report(db)
    log_ticket_message(db, ticket.id, "system", current_user.username, f"Estado cambiado a {status}.")
    audit_log(db, current_user, "update", "SupportTicket", target_id=ticket.id, details=f"Estado cambiado a {status} por {current_user.username}")
    return RedirectResponse(url=f"/support/ticket/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/support/ticket/{ticket_id}/attachments")
async def upload_ticket_attachment(
    request: Request,
    ticket_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado.")
    # permission by plant
    if current_user.role != "admin":
        accessible = get_user_accessible_plant_ids(db, current_user)
        if ticket.plant_id not in accessible:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para adjuntar archivos a este ticket.")

    UPLOAD_DIR = Path("uploads")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{ticket_id}_{int(datetime.utcnow().timestamp())}_{secrets.token_hex(8)}_{file.filename}"
    storage_path = UPLOAD_DIR / safe_name
    contents = await file.read()
    with storage_path.open("wb") as fh:
        fh.write(contents)

    attachment = TicketAttachment(
        ticket_id=ticket.id,
        filename=file.filename,
        content_type=file.content_type,
        storage_path=str(storage_path),
        uploaded_by=current_user.id if current_user else None,
    )
    db.add(attachment)
    db.commit()
    audit_log(db, current_user, "create", "TicketAttachment", target_id=attachment.id, details=f"Adjunto {attachment.filename} subido al ticket {ticket.id}")
    ticket.last_updated = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/support/ticket/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/attachments/{attachment_id}")
def download_attachment(request: Request, attachment_id: int, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Adjunto no encontrado.")
    ticket = db.query(SupportTicket).filter(SupportTicket.id == attachment.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket asociado no encontrado.")
    if current_user.role != "admin":
        accessible = get_user_accessible_plant_ids(db, current_user)
        if ticket.plant_id not in accessible:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para descargar este archivo.")
    path = Path(attachment.storage_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Archivo en disco no encontrado.")
    return FileResponse(path, media_type=attachment.content_type or "application/octet-stream", filename=attachment.filename)


@app.get("/support/report")
def download_support_report(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    report_path = REPORT_DIR / "support_report.md"
    if not report_path.exists():
        generate_support_report(db)
    return FileResponse(report_path, media_type="text/markdown", filename="support_report.md")


@app.get("/reports", response_class=HTMLResponse)
def list_reports(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_files = sorted(REPORT_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    reports = [
        {
            "name": report.name,
            "created_at": datetime.utcfromtimestamp(report.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "size_kb": round(report.stat().st_size / 1024, 2),
        }
        for report in report_files
    ]
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"request": request, "current_user": current_user, "reports": reports},
    )


@app.get("/reports/download")
def download_report(request: Request, file: str, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    safe_name = Path(file).name
    report_path = REPORT_DIR / safe_name
    if not report_path.exists() or report_path.parent != REPORT_DIR:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Informe no encontrado.")
    return FileResponse(report_path, media_type="text/markdown", filename=report_path.name)


@app.get("/help", response_class=HTMLResponse)
def help_center(request: Request, db: Session = Depends(get_db), search: str = ""):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    articles_query = db.query(KnowledgeBaseArticle).order_by(KnowledgeBaseArticle.created_at.desc())
    if search:
        articles_query = articles_query.filter(
            (KnowledgeBaseArticle.title.ilike(f"%{search}%"))
            | (KnowledgeBaseArticle.content.ilike(f"%{search}%"))
            | (KnowledgeBaseArticle.category.ilike(f"%{search}%"))
        )
    articles = articles_query.all()
    return templates.TemplateResponse(
        request,
        "help_center.html",
        {"request": request, "current_user": current_user, "articles": articles, "search": search},
    )


@app.post("/help")
def create_help_article(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    category: str = Form("General"),
    db: Session = Depends(get_db),
):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin", "manager"])
    title_value = sanitize_text(title, "Título del artículo", max_length=128)
    content_value = sanitize_text(content, "Contenido del artículo", max_length=8192)
    category_value = sanitize_text(category, "Categoría", max_length=64)
    article = KnowledgeBaseArticle(title=title_value, content=content_value, category=category_value)
    db.add(article)
    db.commit()
    audit_log(db, current_user, "create", "KnowledgeBaseArticle", target_id=article.id, details=f"Artículo KB creado: {title_value}")
    return RedirectResponse(url="/help", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/employees", response_class=HTMLResponse)
def read_employees(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "50"))
    query = db.query(Employee).order_by(Employee.created_at.desc())
    total = query.count()
    employees = query.offset((page - 1) * page_size).limit(page_size).all()
    return templates.TemplateResponse(
        request,
        "employees.html",
        {"request": request, "current_user": current_user, "employees": employees, "total": total, "page": page, "page_size": page_size},
    )


@app.post("/users")
def create_user(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form(...), db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin"])

    username_value = sanitize_text(username, "Usuario", max_length=64).lower()
    validate_password_strength(password)
    validate_choice(role, ["admin", "manager", "staff", "supervisor"], "rol")

    if db.query(User).filter(User.username == username_value).first():
        return templates.TemplateResponse(
            request,
            "register.html",
            {"request": request, "current_user": current_user, "error": "El usuario ya existe."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(username=username_value, password_hash=pwd_context.hash(password), role=role)
    db.add(user)
    db.commit()
    audit_log(db, current_user, "create", "User", target_id=user.id, details=f"Usuario {username_value} creado")
    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)


def generate_ai_response(message: str, profile: CustomerProfile | None = None, articles: list[KnowledgeBaseArticle] | None = None) -> str:
    question = message.strip().lower()
    tone = ""
    if profile and profile.communication_style:
        tone = profile.communication_style.lower()
    prefix = ""
    if tone == "informal":
        prefix = "Hola! "
    elif tone == "profesional":
        prefix = "Estimado usuario, "
    elif tone == "elegante":
        prefix = "Con gusto le informo que "
    else:
        prefix = ""
    memory_snippet = find_profile_memory(profile, message) if profile else None
    if memory_snippet:
        return f"{prefix}Recuerdo esto de interacciones anteriores: {memory_snippet}. ¿Quieres que lo transforme en un plan de acción?"
    if any(term in question for term in ["ayuda", "problema", "no funciona", "error"]):
        return f"{prefix}Dime más detalles del problema y te propongo una solución paso a paso."
    if any(term in question for term in ["tarea", "asignada", "completada", "urgente"]):
        return f"{prefix}Para una tarea asignada, revisa su estado y confirma si necesita recursos adicionales. Si quieres, puedo ayudarte a priorizarla."
    if any(term in question for term in ["empleado", "personal", "equipo"]):
        return f"{prefix}Puedes comunicarte con el empleado responsable y coordinar el seguimiento. ¿Deseas que te sugiera un mensaje para enviarle?"
    if any(term in question for term in ["notificación", "aviso", "alerta"]):
        return f"{prefix}Las notificaciones se muestran automáticamente cuando una tarea se asigna o se completa. Revisa la sección de notificaciones para ver los detalles."
    if articles:
        relevant = find_relevant_articles(articles, message)
        if relevant:
            result_titles = ", ".join([article.title for article in relevant])
            return f"{prefix}He encontrado artículos relevantes en la base de conocimiento: {result_titles}. Revisa el centro de ayuda para más detalles."
    if any(term in question for term in ["whatsapp", "audio", "voz"]):
        return f"{prefix}La integración WhatsApp y audio está diseñada para mantener conversaciones naturales y con memoria de contexto. Déjame saber qué necesitas en ese canal."
    return f"{prefix}Gracias por tu consulta. Cuéntame con más detalle y te ayudo a definir el siguiente paso."

@app.get("/audit", response_class=HTMLResponse)
def read_audit(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin"])
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(200).all()
    return templates.TemplateResponse(request, "audit.html", {"request": request, "current_user": current_user, "logs": logs})


@app.get("/backup")
def download_backup(request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    require_roles(current_user, ["admin"])
    encrypted_backup = create_encrypted_backup(db)
    return FileResponse(path=encrypted_backup, filename=encrypted_backup.name, media_type="application/octet-stream")


# ============================================================================
# PLANT MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/plants", response_class=HTMLResponse)
def list_plants(request: Request, db: Session = Depends(get_db)):
    """Show all plants that the current user has access to"""
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    
    # Get plants accessible to this user
    user_plant_accesses = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id
    ).all()
    
    plants = [access.plant for access in user_plant_accesses]
    
    # Add gradients for visual variety
    gradients = [
        {"start": "#667eea", "end": "#764ba2"},
        {"start": "#f093fb", "end": "#f5576c"},
        {"start": "#4facfe", "end": "#00f2fe"},
        {"start": "#43e97b", "end": "#38f9d7"},
    ]
    
    for i, plant in enumerate(plants):
        gradient = gradients[i % len(gradients)]
        plant.gradient_start = gradient["start"]
        plant.gradient_end = gradient["end"]
    
    return templates.TemplateResponse(
        request,
        "plant_home.html",
        {"request": request, "current_user": current_user, "plants": plants},
    )


@app.get("/plant/{plant_id}", response_class=HTMLResponse)
def view_plant_dashboard(request: Request, plant_id: int, db: Session = Depends(get_db)):
    """Show plant dashboard with tickets and statistics"""
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    
    # Verify user has access to this plant
    access = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id,
        UserPlantAccess.plant_id == plant_id
    ).first()
    
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta planta.")
    
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada.")
    
    # Get all tickets for this plant
    all_tickets = db.query(SupportTicket).filter(SupportTicket.plant_id == plant_id).all()
    
    # Calculate statistics
    stats = calculate_ticket_stats(all_tickets)
    
    # Filter tickets by status
    tickets_completo = filter_tickets_by_status(all_tickets, "completo")
    tickets_incompleto = filter_tickets_by_status(all_tickets, "incompleto")
    tickets_proceso = filter_tickets_by_status(all_tickets, "proceso")
    
    audit_log(db, current_user, "view", "Plant", target_id=plant_id, details=f"Vio dashboard de planta {plant.name}")
    
    return templates.TemplateResponse(
        request,
        "plant_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "plant": plant,
            "stats": stats,
            "tickets_completo": tickets_completo[:5],  # Show last 5
            "tickets_incompleto": tickets_incompleto[:5],  # Show last 5
            "tickets_proceso": tickets_proceso[:5],
        },
    )


@app.get("/plant/{plant_id}/ticket/new", response_class=HTMLResponse)
def show_plant_ticket_form(request: Request, plant_id: int, db: Session = Depends(get_db)):
    """Show form to create a new ticket for a specific plant"""
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    
    # Verify user has access to this plant
    access = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id,
        UserPlantAccess.plant_id == plant_id
    ).first()
    
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta planta.")
    
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada.")
    
    # Get all employees to assign
    employees = db.query(Employee).all()
    
    return templates.TemplateResponse(
        request,
        "plant_ticket_new.html",
        {"request": request, "current_user": current_user, "plant": plant, "employees": employees},
    )


@app.post("/plant/{plant_id}/ticket/new", response_class=HTMLResponse)
def create_plant_ticket(
    request: Request,
    plant_id: int,
    subject: str = Form(...),
    description: str = Form(...),
    priority: str = Form("normal"),
    assigned_to: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Create a new ticket for a specific plant"""
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    
    # Verify user has access to this plant
    access = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id,
        UserPlantAccess.plant_id == plant_id
    ).first()
    
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta planta.")
    
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada.")
    
    # Validate inputs
    subject_value = sanitize_text(subject, "Asunto", max_length=255)
    description_value = sanitize_text(description, "Descripción", max_length=5000)
    validate_choice(priority, ["baja", "media", "alta", "emergencia"], "prioridad")
    
    # Create ticket
    ticket = SupportTicket(
        user_id=current_user.id,
        plant_id=plant_id,
        subject=subject_value,
        description=description_value,
        priority=priority,
        status="abierto",
        channel="web",
        assigned_to=assigned_to,
    )
    
    db.add(ticket)
    db.commit()
    
    # Notify the assigned employee about the new ticket
    if assigned_to is not None:
        assignee = db.query(Employee).filter(Employee.id == assigned_to).first()
        if assignee and assignee.account:
            notify_user(db, assignee.account.id, f"Nuevo ticket asignado #{ticket.id}: {ticket.subject}", employee_id=assignee.id)
    
    audit_log(db, current_user, "create", "SupportTicket", target_id=ticket.id, details=f"Ticket creado en planta {plant.name}")
    
    # If emergency priority, send WhatsApp notifications to responsible users
    if priority == "emergencia":
        send_emergency_notifications(db, plant_id, ticket, current_user)
    
    return RedirectResponse(url=f"/plant/{plant_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/plant/{plant_id}/tickets/export")
def export_plant_tickets(request: Request, plant_id: int, db: Session = Depends(get_db)):
    """Export plant tickets to Excel with 4 sheets (Completadas, Incompletas, En Proceso, Canceladas)"""
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    
    # Verify user has access
    access = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id,
        UserPlantAccess.plant_id == plant_id
    ).first()
    
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta planta.")
    
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada.")
    
    # Get all tickets
    tickets = db.query(SupportTicket).filter(SupportTicket.plant_id == plant_id).all()
    
    # Export to Excel with multiple sheets
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"tickets_{plant.name.replace(' ', '_')}_{timestamp}.xlsx"
    filepath = f"reports/{filename}"
    
    export_tickets_to_excel_multiple_sheets(tickets, plant.name, filepath)
    
    audit_log(db, current_user, "export", "SupportTicket", target_id=plant_id, details=f"Exportó tickets de {plant.name}")
    
    return FileResponse(filepath, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)


@app.get("/plant/{plant_id}/tickets/report", response_class=HTMLResponse)
def plant_tickets_report(request: Request, plant_id: int, db: Session = Depends(get_db)):
    """Show detailed report of all tickets for a plant"""
    current_user = require_login(request, db)
    if isinstance(current_user, RedirectResponse):
        return current_user
    
    # Verify user has access
    access = db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == current_user.id,
        UserPlantAccess.plant_id == plant_id
    ).first()
    
    if not access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta planta.")
    
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planta no encontrada.")
    
    # Get all tickets
    tickets = db.query(SupportTicket).filter(SupportTicket.plant_id == plant_id).all()
    stats = calculate_ticket_stats(tickets)
    
    return templates.TemplateResponse(
        request,
        "plant_tickets_report.html",
        {
            "request": request,
            "current_user": current_user,
            "plant": plant,
            "tickets": tickets,
            "stats": stats,
        },
    )


def send_emergency_notifications(db: Session, plant_id: int, ticket: SupportTicket, creator: User) -> None:
    """Send WhatsApp notifications for emergency tickets"""
    try:
        # Get plant managers who have access to this plant
        plant = db.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            return
        
        # Find all users with access to this plant who have phone numbers
        user_plant_accesses = db.query(UserPlantAccess).filter(
            UserPlantAccess.plant_id == plant_id
        ).all()
        
        for access in user_plant_accesses:
            user = access.user
            if user.role in ["admin", "manager"]:
                # Get employee profile with phone number
                employee = db.query(Employee).filter(Employee.user_id == user.id).first()
                if employee and employee.phone_number:
                    message = f"🚨 EMERGENCIA en {plant.name}\n\nTicket #{ticket.id}: {ticket.subject}\n\nResponsable: {creator.username}\n\nAcciones: Revisa el sistema inmediatamente."
                    send_whatsapp_notification(employee.phone_number, message)
        
        # Also log the notification
        notification = Notification(
            user_id=creator.id,
            message=f"⚠️ EMERGENCIA - Ticket #{ticket.id} creado: {ticket.subject}"
        )
        db.add(notification)
        db.commit()
        
    except Exception as e:
        print(f"Error sending emergency notifications: {str(e)}")
        pass
