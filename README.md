# Advanced Ticket Management System

Enterprise-style ticket management for multi-plant operations. Built with Python, this system delivers role-aware workflows, SLA tracking, audit-ready reporting, attachments, and secure plant-level access control.

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

This project is designed as a modular Python backend with server-rendered page flows and strong data validation.

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

## Screenshots

> Screenshots can be added to the `screenshots/` folder and referenced here once available.

- `screenshots/01_login.png`
- `screenshots/02_dashboard.png`
- `screenshots/03_ticket_history.png`

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/advanced-ticket-management-system.git
   cd advanced-ticket-management-system
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
   - `DATABASE_URL` (for SQLite or other DB)
   - `SECRET_KEY`
   - `BACKUP_ENCRYPTION_KEY`
   - `ADMIN_PASSWORD`

5. Initialize the database and default admin user:
   ```bash
   python main.py
   ```
   Or ensure the application is started once to create the schema.

## Usage

1. Start the application:
   ```bash
   uvicorn main:app --reload
   ```
2. Open your browser at:
   ```bash
   http://127.0.0.1:8000/login
   ```
3. Use the login page to sign in:
   - Admin user: `admin` / `ADMIN_PASSWORD`
   - Demo user: access `http://127.0.0.1:8000/login/demo`
4. Explore the system:
   - Plant dashboard
   - Ticket queues and SLA tracking
   - Ticket detail views and attachments
   - Automation rules and audit logs
   - Export CSV and reporting pages

## Future Improvements

- Add dedicated API endpoints for third-party integrations
- Implement role-specific dashboards for each user profile
- Add richer analytics and charting widgets
- Build a React/Vue frontend for a modern SPA experience
- Add multi-tenant separation for customer accounts
- Add email/SMS notifications for SLA alerts

## Footer

Advanced Ticket Management System is a complete enterprise ticketing platform for plant operations, designed to deliver security, traceability, and productivity across distributed teams.
