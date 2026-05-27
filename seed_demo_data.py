import os
import csv
import random
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///business.db")
os.environ.setdefault("ADMIN_PASSWORD", "Admin2026!0")

from database import engine, SessionLocal, pwd_context, ensure_schema
from models import (
    Base,
    User,
    Employee,
    Plant,
    UserPlantAccess,
    SupportTicket,
    Task,
    SupportTicketMessage,
    Notification,
    CustomerProfile,
    AuditLog,
    LoginAttempt,
)

EMPLOYEE_ACCOUNTS_CSV = "reports/employee_accounts.csv"
EMPLOYEE_ACCOUNTS_MD = "reports/employee_accounts.md"

EMPLOYEES = [
    {"name": "Camila Rivas", "username": "camila.r", "role": "manager", "password": "Mng2026!A"},
    {"name": "Javier Soto", "username": "javier.s", "role": "manager", "password": "Mng2026!B"},
    {"name": "Lucía Pérez", "username": "lucia.p", "role": "manager", "password": "Mng2026!C"},
    {"name": "Marcos Díaz", "username": "marcos.d", "role": "manager", "password": "Mng2026!D"},
    {"name": "Paula Costa", "username": "paula.c", "role": "manager", "password": "Mng2026!E"},
    {"name": "Andrés Blanco", "username": "andres.b", "role": "staff", "password": "Staff2026!1"},
    {"name": "Sofía Torres", "username": "sofia.t", "role": "staff", "password": "Staff2026!2"},
    {"name": "Diego Ramos", "username": "diego.r", "role": "staff", "password": "Staff2026!3"},
    {"name": "Valentina Cruz", "username": "valentina.c", "role": "staff", "password": "Staff2026!4"},
    {"name": "Pablo Vega", "username": "pablo.v", "role": "staff", "password": "Staff2026!5"},
]

TICKET_TEMPLATES = [
    {
        "subject": "Fuga de vapor en línea principal",
        "description": "Detección de fuga en la tubería de vapor principal. Validar presión y sellado.",
        "priority": "emergencia",
        "status": "incompleto",
        "channel": "web",
    },
    {
        "subject": "Sensor de temperatura fuera de rango",
        "description": "El sensor T-12 reporta valores inconsistentes en planta.",
        "priority": "alta",
        "status": "proceso",
        "channel": "email",
    },
    {
        "subject": "Revisión de tablero eléctrico",
        "description": "Tablero general requiere inspección de seguridad y limpieza.",
        "priority": "media",
        "status": "cancelado",
        "channel": "web",
    },
    {
        "subject": "Actualización de firmware en PLC",
        "description": "Actualizar firmware del controlador lógico programable del área de procesos.",
        "priority": "alta",
        "status": "completo",
        "channel": "web",
    },
    {
        "subject": "Falla intermitente en bomba de agua",
        "description": "La bomba de agua presenta cortes de suministro cada 20 minutos.",
        "priority": "emergencia",
        "status": "incompleto",
        "channel": "email",
    },
    {
        "subject": "Cambio de filtros de aire acondicionado",
        "description": "Programar cambio de filtros de las unidades HVAC.",
        "priority": "baja",
        "status": "completo",
        "channel": "web",
    },
    {
        "subject": "Prueba de generador de respaldo",
        "description": "Realizar prueba mensual del generador y registrar resultados.",
        "priority": "alta",
        "status": "proceso",
        "channel": "email",
    },
    {
        "subject": "Inspección de válvulas de seguridad",
        "description": "Verificar el estado de las válvulas de alivio en línea.",
        "priority": "media",
        "status": "cancelado",
        "channel": "web",
    },
    {
        "subject": "Reporte de ruido excesivo en compresor",
        "description": "El compresor C-3 genera vibraciones y ruidos fuera de estándar.",
        "priority": "alta",
        "status": "incompleto",
        "channel": "email",
    },
    {
        "subject": "Limpieza de tolvas de recepción",
        "description": "Solicitar limpieza profunda de las tolvas de carga.",
        "priority": "baja",
        "status": "completo",
        "channel": "web",
    },
    {
        "subject": "Verificación de alarmas de emergencia",
        "description": "Asegurar que todas las alarmas sonoras y visuales estén activas.",
        "priority": "alta",
        "status": "proceso",
        "channel": "web",
    },
    {
        "subject": "Sobrecalentamiento en motor principal",
        "description": "Motor M-2 alcanza temperaturas críticas en ciclos de producción.",
        "priority": "emergencia",
        "status": "cancelado",
        "channel": "email",
    },
    {
        "subject": "Ajuste de bandeja de alimentación",
        "description": "La bandeja presenta desviación y requiere realineación.",
        "priority": "normal",
        "status": "incompleto",
        "channel": "web",
    },
    {
        "subject": "Revisión de software SCADA",
        "description": "Actualizar componentes del sistema SCADA y revisar logs.",
        "priority": "alta",
        "status": "proceso",
        "channel": "web",
    },
    {
        "subject": "Iluminación insuficiente en pasarela",
        "description": "Agregar luminarias en el acceso de seguridad.",
        "priority": "baja",
        "status": "completo",
        "channel": "email",
    },
    {
        "subject": "Reparación de cinta transportadora",
        "description": "Cinta transportadora C-7 detiene carga de forma irregular.",
        "priority": "emergencia",
        "status": "cancelado",
        "channel": "web",
    },
    {
        "subject": "Revisión de prensa hidráulica",
        "description": "Inspeccionar la prensa y ajustar presión hidráulica.",
        "priority": "alta",
        "status": "incompleto",
        "channel": "web",
    },
    {
        "subject": "Mantenimiento preventivo de rodamientos",
        "description": "Chequear rodamientos de la línea de producción nocturna.",
        "priority": "media",
        "status": "completo",
        "channel": "email",
    },
    {
        "subject": "Desconexión de sistemas redundantes",
        "description": "Programar intervención segura para la desconexión temporal.",
        "priority": "alta",
        "status": "proceso",
        "channel": "web",
    },
    {
        "subject": "Chequeo final de seguridad diaria",
        "description": "Reporte diario de seguridad operativa y control de accesos.",
        "priority": "normal",
        "status": "cancelado",
        "channel": "email",
    },
]

PLANT_CREATE_DATA = [
    {"name": "Planta 1 - Centro", "location": "Centro de la Ciudad", "description": "Planta principal de operaciones"},
    {"name": "Planta 2 - Norte", "location": "Zona Norte", "description": "Planta de distribución norte"},
    {"name": "Planta 3 - Sur", "location": "Zona Sur", "description": "Planta de manufactura sur"},
    {"name": "Planta 4 - Este", "location": "Zona Este", "description": "Planta de servicios este"},
]

TASK_TEMPLATES = [
    {"title": "Inspección de seguridad diaria", "description": "Revisar estado general y reportar anomalías.", "priority": "medium", "status": "pending"},
    {"title": "Revisión de tablero de control", "description": "Validar conexiones y tablero de control.", "priority": "high", "status": "in_progress"},
    {"title": "Limpieza de filtros", "description": "Retirar y limpiar filtros de aire.", "priority": "low", "status": "completed"},
    {"title": "Ajuste de válvulas", "description": "Ajustar válvulas de presión según protocolo.", "priority": "high", "status": "pending"},
    {"title": "Chequeo de iluminación", "description": "Revisar todas las luminarias de la instalación.", "priority": "medium", "status": "in_progress"},
    {"title": "Actualización de inventario", "description": "Registrar materiales y repuestos disponibles.", "priority": "low", "status": "completed"},
    {"title": "Revisión de bombas", "description": "Inspeccionar bombas hidráulicas y reportar vibraciones.", "priority": "high", "status": "pending"},
    {"title": "Prueba de emergencia", "description": "Ejecutar prueba de corte y respaldo de energía.", "priority": "high", "status": "in_progress"},
    {"title": "Evaluación de temperatura", "description": "Monitorear la temperatura de los equipos principales.", "priority": "medium", "status": "pending"},
    {"title": "Ajuste de bandeja", "description": "Realinear bandejas de carga para evitar obstrucciones.", "priority": "low", "status": "completed"},
]

def create_plants(db):
    plants = db.query(Plant).all()
    if plants:
        return plants
    for plant_data in PLANT_CREATE_DATA:
        plant = Plant(**plant_data)
        db.add(plant)
    db.commit()
    return db.query(Plant).all()


def clear_existing_data(db, admin_user):
    db.query(SupportTicketMessage).delete()
    db.query(SupportTicket).delete()
    db.query(Task).delete()
    db.query(UserPlantAccess).delete()
    db.query(Notification).delete()
    db.query(CustomerProfile).delete()
    db.query(AuditLog).filter(AuditLog.user_id != admin_user.id).delete()
    db.query(LoginAttempt).delete()
    db.query(Employee).filter(Employee.user_id != admin_user.id).delete()
    db.query(User).filter(User.username != "admin").delete()
    db.commit()


def ensure_admin_access(db, admin_user):
    plants = db.query(Plant).all()
    for plant in plants:
        existing_access = db.query(UserPlantAccess).filter(
            UserPlantAccess.user_id == admin_user.id,
            UserPlantAccess.plant_id == plant.id,
        ).first()
        if not existing_access:
            db.add(UserPlantAccess(user_id=admin_user.id, plant_id=plant.id))
    db.commit()


def create_employees(db):
    user_employee_map = []
    plants = sorted(db.query(Plant).all(), key=lambda plant: plant.id)
    plant_ids = [plant.id for plant in plants]

    for index, account in enumerate(EMPLOYEES):
        user = User(
            username=account["username"],
            password_hash=pwd_context.hash(account["password"], scheme="pbkdf2_sha256"),
            role=account["role"],
        )
        db.add(user)
        db.flush()

        employee = Employee(
            name=account["name"],
            role=account["role"],
            user_id=user.id,
        )
        db.add(employee)
        db.flush()

        for plant_id in plant_ids:
            db.add(UserPlantAccess(user_id=user.id, plant_id=plant_id))

        user_employee_map.append({
            "user": user,
            "employee": employee,
            "password": account["password"],
        })

    db.commit()
    return user_employee_map


def create_tickets(db, employees, plants):
    ticket_rows = []
    author_users = [item["user"] for item in employees]
    assignee_employees = [item["employee"] for item in employees]
    now = datetime.utcnow()

    for plant in plants:
        for idx, template in enumerate(TICKET_TEMPLATES):
            assignee = random.choice(assignee_employees)
            author = random.choice(author_users)
            ticket = SupportTicket(
                user_id=author.id,
                plant_id=plant.id,
                subject=template["subject"],
                description=template["description"],
                channel=template["channel"],
                priority=template["priority"],
                status=template["status"],
                assigned_to=assignee.id,
                created_at=now - timedelta(days=(idx + plant.id * 2)),
                last_updated=now - timedelta(days=max(0, idx - 1)),
            )
            db.add(ticket)
            ticket_rows.append(ticket)

    db.commit()
    return ticket_rows


def create_ticket_notifications(db, tickets):
    created = 0
    for ticket in tickets:
        if ticket.assigned_employee and ticket.assigned_employee.account:
            user_id = ticket.assigned_employee.account.id
            message = f"Ticket asignado #{ticket.id}: {ticket.subject} (estado: {ticket.status}, prioridad: {ticket.priority})."
            exists = db.query(Notification).filter(Notification.user_id == user_id, Notification.message == message).first()
            if not exists:
                db.add(Notification(user_id=user_id, employee_id=ticket.assigned_to, message=message))
                created += 1
    db.commit()
    return created


def create_tasks(db, employees, plants):
    task_rows = []
    assignee_employees = [item["employee"] for item in employees]
    now = datetime.utcnow()

    for plant in plants:
        for idx, template in enumerate(TASK_TEMPLATES):
            assignee = random.choice(assignee_employees)
            task = Task(
                title=template["title"],
                description=template["description"],
                priority=template["priority"],
                status=template["status"],
                assigned_to=assignee.id,
                plant_id=plant.id,
                created_at=now - timedelta(days=(idx + plant.id))
            )
            db.add(task)
            task_rows.append(task)

    db.commit()
    return task_rows


def write_employee_documents(employees):
    os.makedirs("reports", exist_ok=True)
    with open(EMPLOYEE_ACCOUNTS_CSV, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["name", "role", "username", "password"])
        for item in employees:
            writer.writerow([item["employee"].name, item["employee"].role, item["user"].username, item["password"]])

    with open(EMPLOYEE_ACCOUNTS_MD, "w", encoding="utf-8") as md_file:
        md_file.write("# Empleados generados\n\n")
        md_file.write("| Nombre | Rol | Usuario | Contraseña |\n")
        md_file.write("|---|---|---|---|\n")
        for item in employees:
            md_file.write(
                f"| {item['employee'].name} | {item['employee'].role} | {item['user'].username} | {item['password']} |\n"
            )


def main():
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    admin_user = db.query(User).filter(User.username == "admin").first()
    if not admin_user:
        admin_user = User(
            username="admin",
            password_hash=pwd_context.hash(os.environ["ADMIN_PASSWORD"], scheme="pbkdf2_sha256"),
            role="admin",
        )
        db.add(admin_user)
        db.commit()

    plants = create_plants(db)
    clear_existing_data(db, admin_user)
    ensure_admin_access(db, admin_user)
    employees = create_employees(db)
    tickets = create_tickets(db, employees, plants)
    created_notifications = create_ticket_notifications(db, tickets)
    tasks = create_tasks(db, employees, plants)
    write_employee_documents(employees)

    print("Datos generados correctamente:")
    print(f"  - Notificaciones de tickets creadas: {created_notifications}")
    print(f"  - Usuarios empleados creados: {len(employees)}")
    print(f"  - Tickets creados: {len(tickets)}")
    print(f"  - Tareas creadas: {len(tasks)}")
    print(f"  - Documento CSV: {os.path.abspath(EMPLOYEE_ACCOUNTS_CSV)}")
    print(f"  - Documento Markdown: {os.path.abspath(EMPLOYEE_ACCOUNTS_MD)}")
    print("\n💡 El admin sigue siendo el usuario 'admin'.")

    db.close()


if __name__ == "__main__":
    main()
