"""
Script to create example tickets and export to Excel
Run: python create_sample_tickets.py
"""

from database import get_db, engine
from models import Base, Plant, User, UserPlantAccess, SupportTicket, Employee
from plant_utils import export_tickets_to_excel, calculate_ticket_stats
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import os


def create_sample_tickets():
    """Create sample tickets for demonstration"""
    
    # Set database URL if needed
    os.environ.setdefault("DATABASE_URL", "sqlite:///business.db")
    
    db = next(get_db())
    
    # Get first plant
    plant = db.query(Plant).first()
    if not plant:
        print("❌ No plants found. Run init_plants.py first.")
        db.close()
        return
    
    # Get first user
    user = db.query(User).first()
    if not user:
        print("❌ No users found.")
        db.close()
        return
    
    # Get or create admin employee
    admin_employee = db.query(Employee).first()
    if not admin_employee:
        admin_employee = Employee(name="Admin", role="admin", user_id=user.id)
        db.add(admin_employee)
        db.commit()
    
    # Clear existing tickets
    existing = db.query(SupportTicket).filter(SupportTicket.plant_id == plant.id).all()
    for ticket in existing:
        db.delete(ticket)
    db.commit()
    
    print(f"📋 Creating sample tickets for {plant.name}...\n")
    
    # Sample tickets data
    tickets_data = [
        {
            "subject": "Falla en sistema de enfriamiento",
            "description": "El sistema de enfriamiento de la planta está presentando problemas. La temperatura ha aumentado 5 grados en las últimas 2 horas.",
            "priority": "emergencia",
            "status": "abierto"
        },
        {
            "subject": "Mantenimiento de compresores",
            "description": "Programar mantenimiento preventivo de los compresores según protocolo.",
            "priority": "alta",
            "status": "proceso"
        },
        {
            "subject": "Calibración de sensores",
            "description": "Los sensores de presión necesitan recalibración.",
            "priority": "media",
            "status": "proceso"
        },
        {
            "subject": "Inspección de tuberías",
            "description": "Revisión completa del sistema de tuberías para detectar posibles fugas.",
            "priority": "media",
            "status": "completo"
        },
        {
            "subject": "Limpieza de filtros",
            "description": "Cambio y limpieza de filtros del sistema de aire acondicionado.",
            "priority": "baja",
            "status": "completo"
        },
        {
            "subject": "Instalación de nuevos medidores",
            "description": "Instalación de medidores digitales de energía.",
            "priority": "media",
            "status": "proceso"
        },
        {
            "subject": "Reparación de bomba hidráulica",
            "description": "La bomba hidráulica principal está presentando ruidos extraños.",
            "priority": "alta",
            "status": "abierto"
        },
        {
            "subject": "Revisión de luces de emergencia",
            "description": "Inspección y prueba de todas las luces de emergencia.",
            "priority": "baja",
            "status": "completo"
        },
    ]
    
    # Create tickets with different dates
    base_date = datetime.utcnow()
    for i, ticket_data in enumerate(tickets_data):
        ticket = SupportTicket(
            user_id=user.id,
            plant_id=plant.id,
            subject=ticket_data["subject"],
            description=ticket_data["description"],
            priority=ticket_data["priority"],
            status=ticket_data["status"],
            channel="web",
            assigned_to=admin_employee.id,
            created_at=base_date - timedelta(days=i),
            last_updated=base_date - timedelta(days=i//2)
        )
        db.add(ticket)
        print(f"✅ {ticket.subject}")
        print(f"   Estado: {ticket.status} | Prioridad: {ticket.priority}\n")
    
    db.commit()
    
    # Get all tickets
    all_tickets = db.query(SupportTicket).filter(SupportTicket.plant_id == plant.id).all()
    stats = calculate_ticket_stats(all_tickets)
    
    print("\n📊 Estadísticas:")
    print(f"   Total: {stats['total']}")
    print(f"   ✅ Completados: {stats['completo']} ({stats['completo_percent']}%)")
    print(f"   🔴 Incompletos: {stats['incompleto']} ({stats['incompleto_percent']}%)")
    print(f"   ⏳ En Proceso: {stats['proceso']} ({stats['proceso_percent']}%)")
    
    # Export to Excel
    print(f"\n📥 Exporting to Excel...")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"tickets_{plant.name.replace(' ', '_')}_{timestamp}.xlsx"
    filepath = f"reports/{filename}"
    
    export_tickets_to_excel(all_tickets, plant.name, filepath)
    
    print(f"\n✅ Excel file created: {filepath}")
    print(f"\n📍 Full path: {os.path.abspath(filepath)}")
    
    db.close()
    
    return filepath


if __name__ == "__main__":
    print("🌱 Creating sample tickets...\n")
    excel_path = create_sample_tickets()
    print("\n✅ Done! You can now download and open the Excel file.")
