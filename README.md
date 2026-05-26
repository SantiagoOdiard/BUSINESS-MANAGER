# BUSINESS-MANAGER

Advanced ticket management system with SLA, automation, role-based access control and audit logging built in Python.

## Features

- ✅ Multi-plant ticket management
- ✅ Role-based access control (`Admin`, `Manager`, `Supervisor`, `Staff`)
- ✅ Ticket assignment and status workflow
- ✅ SLA deadlines and overdue ticket detection
- ✅ Ticket conversations, internal notes, and history
- ✅ File attachments with secure downloads
- ✅ Notification system with live refresh
- ✅ CSV export for tickets and task reports
- ✅ Audit log tracking for user actions
- ✅ Search, filters, and pagination
- ✅ Automation rules and routing
- ✅ Dashboard metrics and operational reporting
- ✅ User permissions scoped by plant

## Architecture Overview

This project is designed as a modular Python backend with server-rendered pages, secure authentication, and strong data validation.

- `main.py` contains the FastAPI routes, authentication flow, business logic, and access validation.
- `models.py` defines the SQLAlchemy ORM models for users, plants, tickets, messages, tasks, notifications, attachments, and audit logs.
- `database.py` initializes the database connection, schema enforcement, and migration helpers.
- Templates render the UI with Jinja2 and provide a streamlined enterprise experience.
- Static assets deliver polished layout, forms, buttons, and notification styling.

## Technologies Used

- Python
- FastAPI
- SQLAlchemy
- Jinja2 templates
- SQLite / SQL database
- Passlib password hashing
- Itsdangerous session signing
- Standard Python libraries for security and file handling

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/SantiagoOdiard/BUSINESS-MANAGER.git
   cd BUSINESS-MANAGER
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables:
   - `DATABASE_URL`
   - `SECRET_KEY`
   - `BACKUP_ENCRYPTION_KEY`
   - `ADMIN_PASSWORD`

5. Initialize the database and start the app:
   ```bash
   uvicorn main:app --reload
   ```

## Usage

1. Open the browser at:
   ```bash
   http://127.0.0.1:8000/login
   ```
2. Use the login page to sign in.
3. Explore tickets, dashboards, automation rules, audit logs, and exports.

## Future Improvements

- Add dedicated API endpoints for third-party integrations
- Implement role-specific dashboards for each user profile
- Build a modern SPA frontend
- Add email/SMS notifications for SLA alerts

Advanced Ticket Management System is a complete enterprise ticketing platform for plant operations, designed to deliver security, traceability, and productivity across distributed teams.
