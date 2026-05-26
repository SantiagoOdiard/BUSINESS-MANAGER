import os
from database import SessionLocal
from models import User, Employee, Plant, UserPlantAccess
from seed_demo_data import EMPLOYEES

os.environ.setdefault("DATABASE_URL", "sqlite:///business.db")
os.environ.setdefault("ADMIN_PASSWORD", "Admin2026!0")

ACCESS_ASSIGNMENTS = [
    (5, [4]),
    (5, [3]),
    (4, [2]),
    (4, [1]),
    (3, [1, 2, 3, 4]),
]


def get_plants(db):
    return {plant.id: plant for plant in db.query(Plant).order_by(Plant.id).all()}


def run():
    db = SessionLocal()
    try:
        plants = get_plants(db)
        plant_ids = sorted(plants.keys())

        if not plant_ids:
            print("No hay plantas registradas.")
            return

        assignments = []
        cursor = 0
        for count, target_plants in ACCESS_ASSIGNMENTS:
            for _ in range(count):
                if cursor >= len(EMPLOYEES):
                    break
                assignments.append(target_plants)
                cursor += 1
            if cursor >= len(EMPLOYEES):
                break

        print(f"Procesando {len(assignments)} empleados para acceso por planta...")

        for idx, account in enumerate(EMPLOYEES[: len(assignments)]):
            user = db.query(User).filter(User.username == account["username"]).first()
            if not user:
                print(f"Usuario no encontrado: {account['username']}")
                continue

            # Eliminar accesos previos
            db.query(UserPlantAccess).filter(UserPlantAccess.user_id == user.id).delete()

            selected_plant_ids = assignments[idx]
            for plant_id in selected_plant_ids:
                if plant_id not in plants:
                    print(f"Planta {plant_id} no existe; se omite para {user.username}")
                    continue
                db.add(UserPlantAccess(user_id=user.id, plant_id=plant_id))

            plant_names = [plants[pid].name for pid in selected_plant_ids if pid in plants]
            print(f"{user.username}: {plant_names}")

        db.commit()
        print("Accesos por planta corregidos.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
