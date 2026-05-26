"""
Script to create sample tickets for all 4 plants and export to Excel
Run: python create_all_plant_excels.py
"""

from database import get_db, engine
from models import Base, Plant, User, UserPlantAccess, SupportTicket, Employee
from plant_utils import export_tickets_to_excel_multiple_sheets, calculate_ticket_stats
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import os


def create_sample_tickets_for_all_plants():
    """Create sample tickets for each plant"""
    
    # Set database URL if needed
    os.environ.setdefault("DATABASE_URL", "sqlite:///business.db")
    
    db = next(get_db())
    
    # Get all plants
    plants = db.query(Plant).all()
    if not plants:
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
    for plant in plants:
        existing = db.query(SupportTicket).filter(SupportTicket.plant_id == plant.id).all()
        for ticket in existing:
            db.delete(ticket)
    db.commit()
    
    print("📋 Creating sample tickets for all 4 plants...\n")
    
    # Diferentes tipos de tickets para cada planta
    plant_tickets = {
        0: [  # Planta 1
            {"subject": "🚨 Falla en sistema de enfriamiento", "priority": "emergencia", "status": "abierto"},
            {"subject": "Mantenimiento de compresores", "priority": "alta", "status": "proceso"},
            {"subject": "Calibración de sensores", "priority": "media", "status": "proceso"},
            {"subject": "Inspección de tuberías", "priority": "media", "status": "completo"},
            {"subject": "Limpieza de filtros", "priority": "baja", "status": "completo"},
            {"subject": "Instalación de nuevos medidores", "priority": "media", "status": "proceso"},
            {"subject": "Reparación de bomba hidráulica", "priority": "alta", "status": "abierto"},
            {"subject": "Revisión de luces de emergencia", "priority": "baja", "status": "completo"},
        ],
        1: [  # Planta 2
            {"subject": "⚠️ Problema en línea de producción", "priority": "emergencia", "status": "abierto"},
            {"subject": "Cambio de aceite de máquinas", "priority": "alta", "status": "completo"},
            {"subject": "Reparación de banda transportadora", "priority": "alta", "status": "proceso"},
            {"subject": "Inspección de soldaduras", "priority": "media", "status": "proceso"},
            {"subject": "Mantenimiento de motor principal", "priority": "media", "status": "completo"},
            {"subject": "Limpieza de área de trabajo", "priority": "baja", "status": "completo"},
            {"subject": "Revisión de conexiones eléctricas", "priority": "media", "status": "proceso"},
        ],
        2: [  # Planta 3
            {"subject": "🚨 Apagón en sección norte", "priority": "emergencia", "status": "proceso"},
            {"subject": "Revisión de transformadores", "priority": "alta", "status": "abierto"},
            {"subject": "Mantenimiento de generador", "priority": "alta", "status": "completo"},
            {"subject": "Inspección de cableado", "priority": "media", "status": "completo"},
            {"subject": "Cambio de fusibles", "priority": "media", "status": "completo"},
            {"subject": "Limpieza de paneles", "priority": "baja", "status": "proceso"},
            {"subject": "Capacitación de seguridad", "priority": "baja", "status": "completo"},
            {"subject": "Prueba de sistemas de respaldo", "priority": "media", "status": "proceso"},
        ],
        3: [  # Planta 4
            {"subject": "⚠️ Falla en sistema de almacenamiento", "priority": "emergencia", "status": "abierto"},
            {"subject": "Reorganización de inventario", "priority": "alta", "status": "proceso"},
            {"subject": "Revisión de estanterías", "priority": "media", "status": "completo"},
            {"subject": "Reparación de puertas automáticas", "priority": "media", "status": "abierto"},
            {"subject": "Instalación de sistema de CCTV", "priority": "alta", "status": "proceso"},
            {"subject": "Limpieza profunda del área", "priority": "baja", "status": "completo"},
            {"subject": "Actualización de software de gestión", "priority": "media", "status": "proceso"},
            {"subject": "Entrenamiento de personal", "priority": "baja", "status": "completo"},
            {"subject": "Inspección de seguridad", "priority": "media", "status": "completo"},
        ]
    }
    
    excel_files = []
    base_date = datetime.utcnow()
    
    # Create tickets for each plant
    for plant_idx, plant in enumerate(plants):
        if plant_idx not in plant_tickets:
            continue
            
        tickets_data = plant_tickets[plant_idx]
        
        print(f"📍 {plant.name}")
        print(f"   Descripción: {plant.description}")
        print(f"   Ubicación: {plant.location}\n")
        
        # Create tickets
        for i, ticket_data in enumerate(tickets_data):
            ticket = SupportTicket(
                user_id=user.id,
                plant_id=plant.id,
                subject=ticket_data["subject"],
                description=f"Descripción detallada del ticket: {ticket_data['subject']}",
                priority=ticket_data["priority"],
                status=ticket_data["status"],
                channel="web",
                assigned_to=admin_employee.id,
                created_at=base_date - timedelta(days=i),
                last_updated=base_date - timedelta(days=i//2)
            )
            db.add(ticket)
            priority_emoji = "🚨" if ticket_data["priority"] == "emergencia" else "⚠️" if ticket_data["priority"] == "alta" else "ℹ️"
            print(f"   ✅ {ticket_data['subject']}")
        
        db.commit()
        
        # Get all tickets for this plant
        all_tickets = db.query(SupportTicket).filter(SupportTicket.plant_id == plant.id).all()
        stats = calculate_ticket_stats(all_tickets)
        
        print(f"\n   📊 Estadísticas:")
        print(f"      Total: {stats['total']}")
        print(f"      ✅ Completados: {stats['completo']} ({stats['completo_percent']}%)")
        print(f"      🔴 Incompletos: {stats['incompleto']} ({stats['incompleto_percent']}%)")
        print(f"      ⏳ En Proceso: {stats['proceso']} ({stats['proceso_percent']}%)")
        
        # Export to Excel
        print(f"\n   📥 Exporting to Excel...\n")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"tickets_{plant.name.replace(' ', '_')}_{timestamp}.xlsx"
        filepath = f"reports/{filename}"
        
        export_tickets_to_excel_multiple_sheets(all_tickets, plant.name, filepath)
        
        print(f"   ✅ Excel file created: {filepath}\n")
        excel_files.append({
            "plant": plant.name,
            "filepath": filepath,
            "tickets": len(all_tickets)
        })
    
    db.close()
    
    # Summary
    print("\n" + "="*70)
    print("✅ EXCEL FILES GENERATED SUCCESSFULLY")
    print("="*70)
    for item in excel_files:
        print(f"\n📁 {item['plant']}")
        print(f"   📊 Tickets: {item['tickets']}")
        print(f"   📍 Path: {item['filepath']}")
        print(f"   📍 Full Path: {os.path.abspath(item['filepath'])}")
    
    print("\n" + "="*70)
    print("✅ Done! You can now access the Excel files from the platform.")
    print("="*70)
    
    return excel_files


if __name__ == "__main__":
    create_sample_tickets_for_all_plants()
