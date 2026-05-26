"""
Script to initialize plants and assign them to users
Run this after applying the migration: python init_plants.py
"""

from database import get_db, engine
from models import Base, Plant, User, UserPlantAccess
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import os


def init_plants():
    """Create default plants and assign to users"""
    
    # Create database tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    db = next(get_db())
    
    # Check if plants already exist
    existing_plants = db.query(Plant).count()
    if existing_plants > 0:
        print(f"✅ Already have {existing_plants} plants. Skipping initialization.")
        db.close()
        return
    
    # Create 4 plants
    plants_data = [
        {
            "name": "Planta 1 - Centro",
            "location": "Centro de la Ciudad",
            "description": "Planta principal de operaciones"
        },
        {
            "name": "Planta 2 - Norte",
            "location": "Zona Norte",
            "description": "Planta de distribución norte"
        },
        {
            "name": "Planta 3 - Sur",
            "location": "Zona Sur",
            "description": "Planta de manufactura sur"
        },
        {
            "name": "Planta 4 - Este",
            "location": "Zona Este",
            "description": "Planta de servicios este"
        }
    ]
    
    plants = []
    for plant_data in plants_data:
        plant = Plant(
            name=plant_data["name"],
            location=plant_data["location"],
            description=plant_data["description"]
        )
        db.add(plant)
        plants.append(plant)
    
    db.commit()
    print(f"✅ Created {len(plants)} plants")
    
    # Assign plants to all users
    users = db.query(User).all()
    print(f"\nAssigning plants to {len(users)} users:")
    
    for user in users:
        # Give each user access to all plants
        for plant in plants:
            # Check if access already exists
            existing_access = db.query(UserPlantAccess).filter(
                UserPlantAccess.user_id == user.id,
                UserPlantAccess.plant_id == plant.id
            ).first()
            
            if not existing_access:
                access = UserPlantAccess(user_id=user.id, plant_id=plant.id)
                db.add(access)
        
        print(f"  - {user.username}: Acceso a {len(plants)} plantas")
    
    db.commit()
    print(f"\n✅ Plant initialization completed!")
    db.close()


if __name__ == "__main__":
    print("🌱 Initializing plants...")
    init_plants()
    print("\n✅ Done!")
