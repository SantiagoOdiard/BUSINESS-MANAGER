import os
from database import SessionLocal
from models import SupportTicket, Notification


def generate_ticket_notifications():
    db = SessionLocal()
    try:
        tickets = db.query(SupportTicket).filter(SupportTicket.assigned_to != None).all()
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
        print(f"Se crearon {created} notificaciones de tickets asignados.")
    finally:
        db.close()


if __name__ == "__main__":
    generate_ticket_notifications()
