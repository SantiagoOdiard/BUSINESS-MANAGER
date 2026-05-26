# PLANT MANAGEMENT ENDPOINTS - Agregar al final de main.py

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


@app.post("/plant/{plant_id}/ticket/new", response_class=HTMLResponse)
def create_plant_ticket(
    request: Request,
    plant_id: int,
    subject: str = Form(...),
    description: str = Form(...),
    priority: str = Form("normal"),
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
    )
    
    db.add(ticket)
    db.commit()
    
    audit_log(db, current_user, "create", "SupportTicket", target_id=ticket.id, details=f"Ticket creado en planta {plant.name}")
    
    # If emergency priority, send WhatsApp notifications to responsible users
    if priority == "emergencia":
        send_emergency_notifications(db, plant_id, ticket, current_user)
    
    return RedirectResponse(url=f"/plant/{plant_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/plant/{plant_id}/tickets/export")
def export_plant_tickets(request: Request, plant_id: int, db: Session = Depends(get_db)):
    """Export plant tickets to Excel"""
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
    
    # Export to Excel
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"tickets_{plant.name.replace(' ', '_')}_{timestamp}.xlsx"
    filepath = f"reports/{filename}"
    
    export_tickets_to_excel(tickets, plant.name, filepath)
    
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
