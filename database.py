import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from models import Base, User

# Try to use DATABASE_URL if provided, otherwise use SQLite
_db_url = os.getenv("DATABASE_URL")
if _db_url and not _db_url.startswith("sqlite"):
    DATABASE_URL = _db_url
else:
    DATABASE_URL = "sqlite:///./business_manager.db"

DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not DEFAULT_ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD debe configurarse en variables de entorno para la cuenta de administrador inicial.")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
    # Test connection
    with engine.connect() as conn:
        pass
except Exception as e:
    print(f"⚠️  Database connection failed: {e}")
    print("Falling back to SQLite...")
    DATABASE_URL = "sqlite:///./business_manager.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    """Create tables if they don't exist - handles connection errors gracefully"""
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"⚠️  Could not create tables: {e}")
        # Don't crash if schema creation fails, it will be retried on first request
        return
    
    # Only apply schema migrations if using SQLite
    if not DATABASE_URL.startswith("sqlite"):
        return
        
    try:
        with engine.connect() as connection:
            result = connection.execute(text("PRAGMA table_info(employees)"))
            columns = [row[1] for row in result]
            if "user_id" not in columns:
                connection.execute(text("ALTER TABLE employees ADD COLUMN user_id INTEGER"))

            result = connection.execute(text("PRAGMA table_info(notifications)"))
            columns = [row[1] for row in result]
            notnull_map = {row[1]: row[3] for row in connection.execute(text("PRAGMA table_info(notifications)"))}
            if "user_id" not in columns:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN user_id INTEGER"))
            if "employee_id" not in columns:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN employee_id INTEGER"))
            elif notnull_map.get("employee_id") == 1:
                connection.execute(text("PRAGMA foreign_keys=off"))
                connection.execute(text("DROP TABLE IF EXISTS notifications_new"))
                connection.execute(text("CREATE TABLE notifications_new (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, employee_id INTEGER, message TEXT NOT NULL, read BOOLEAN DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
                connection.execute(text("INSERT INTO notifications_new (id, user_id, employee_id, message, read, created_at) SELECT id, user_id, employee_id, message, read, created_at FROM notifications"))
                connection.execute(text("DROP TABLE notifications"))
                connection.execute(text("ALTER TABLE notifications_new RENAME TO notifications"))
                connection.execute(text("PRAGMA foreign_keys=on"))

            result = connection.execute(text("PRAGMA table_info(tasks)"))
            columns = [row[1] for row in result]
            if "plant_id" not in columns:
                connection.execute(text("ALTER TABLE tasks ADD COLUMN plant_id INTEGER DEFAULT 1"))

            result = connection.execute(text("PRAGMA table_info(users)"))
            columns = [row[1] for row in result]
            if "failed_login_attempts" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0"))
            if "last_failed_login_at" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN last_failed_login_at DATETIME"))
            if "locked_until" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN locked_until DATETIME"))
            if "mfa_enabled" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN DEFAULT 0"))
            if "mfa_secret" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN mfa_secret VARCHAR(255)"))

            result = connection.execute(text("PRAGMA table_info(support_tickets)"))
            columns = [row[1] for row in result]
            if "channel" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN channel VARCHAR(255) DEFAULT 'email'"))
            if "priority" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN priority VARCHAR(255) DEFAULT 'normal'"))
            if "assigned_to" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN assigned_to INTEGER"))
            if "email_from" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN email_from VARCHAR(255)"))
            if "email_message_id" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN email_message_id VARCHAR(255)"))
            if "received_at" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN received_at DATETIME"))
            if "sla_due" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN sla_due DATETIME"))
            if "last_updated" not in columns:
                connection.execute(text("ALTER TABLE support_tickets ADD COLUMN last_updated DATETIME"))
            # Ensure attachments table exists for uploaded files
            connection.execute(text("CREATE TABLE IF NOT EXISTS ticket_attachments (id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, filename VARCHAR(1024) NOT NULL, content_type VARCHAR(255), storage_path VARCHAR(2048) NOT NULL, uploaded_by INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
    except Exception as e:
        print(f"⚠️  Could not apply schema migrations: {e}")
        # Continue anyway - tables were created, migrations can be applied later


def create_default_admin():
    try:
        ensure_schema()
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").first()
            if not admin:
                admin = User(
                    username="admin",
                    password_hash=pwd_context.hash(DEFAULT_ADMIN_PASSWORD),
                    role="admin",
                )
                db.add(admin)
                db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"⚠️  Could not create default admin: {e}")
        # Don't crash if admin creation fails, it will be created on first access


# Don't call on import, let main.py call it after app is set up
