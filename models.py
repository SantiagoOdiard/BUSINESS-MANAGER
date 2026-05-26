from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default='staff')
    created_at = Column(DateTime, default=datetime.utcnow)

    audits = relationship('AuditLog', back_populates='user')
    employee_profile = relationship('Employee', back_populates='account', uselist=False)
    notifications = relationship('Notification', back_populates='recipient')
    support_tickets = relationship('SupportTicket', back_populates='user')
    failed_login_attempts = Column(Integer, default=0)
    last_failed_login_at = Column(DateTime, nullable=True)
    locked_until = Column(DateTime, nullable=True)
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String, nullable=True)


class Employee(Base):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    phone_number = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tasks = relationship('Task', back_populates='employee')
    account = relationship('User', back_populates='employee_profile')


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default='')
    priority = Column(String, nullable=False)
    status = Column(String, nullable=False)
    assigned_to = Column(Integer, ForeignKey('employees.id'))
    plant_id = Column(Integer, ForeignKey('plants.id'), nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship('Employee', back_populates='tasks')
    plant = relationship('Plant')


class Notification(Base):
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    message = Column(Text, nullable=False)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=True)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    recipient = relationship('User', back_populates='notifications')
    employee = relationship('Employee')


class SupportTicket(Base):
    __tablename__ = 'support_tickets'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    plant_id = Column(Integer, ForeignKey('plants.id'), nullable=False, default=1)
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    channel = Column(String, nullable=False, default='email')
    priority = Column(String, nullable=False, default='normal')
    status = Column(String, nullable=False, default='open')
    assigned_to = Column(Integer, ForeignKey('employees.id'), nullable=True)
    email_from = Column(String, nullable=True)
    email_message_id = Column(String, nullable=True)
    received_at = Column(DateTime, nullable=True)
    sla_due = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='support_tickets')
    plant = relationship('Plant', back_populates='support_tickets')
    assigned_employee = relationship('Employee')
    messages = relationship('SupportTicketMessage', back_populates='ticket', cascade='all, delete-orphan')
    attachments = relationship('TicketAttachment', back_populates='ticket', cascade='all, delete-orphan')


class SupportTicketMessage(Base):
    __tablename__ = 'support_ticket_messages'

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey('support_tickets.id'), nullable=False)
    sender_type = Column(String, nullable=False)
    sender_name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    internal = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship('SupportTicket', back_populates='messages')


class CustomerProfile(Base):
    __tablename__ = 'customer_profiles'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    company = Column(String, nullable=True)
    preferences = Column(Text, nullable=True)
    communication_style = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User')


class AutomationRule(Base):
    __tablename__ = 'automation_rules'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    condition_type = Column(String, nullable=False)
    condition_value = Column(String, nullable=False)
    action_set_priority = Column(String, nullable=True)
    action_set_status = Column(String, nullable=True)
    action_assign_to = Column(Integer, ForeignKey('employees.id'), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    assignee = relationship('Employee')


class KnowledgeBaseArticle(Base):
    __tablename__ = 'knowledge_base_articles'

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    category = Column(String, nullable=False, default='General')
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    action = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    target_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='audits')


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    ip_address = Column(String, nullable=False)
    success = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Plant(Base):
    __tablename__ = 'plants'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    location = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user_accesses = relationship('UserPlantAccess', back_populates='plant', cascade='all, delete-orphan')
    support_tickets = relationship('SupportTicket', back_populates='plant')


class UserPlantAccess(Base):
    __tablename__ = 'user_plant_access'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    plant_id = Column(Integer, ForeignKey('plants.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', backref='plant_accesses')
    plant = relationship('Plant', back_populates='user_accesses')


class TicketAttachment(Base):
    __tablename__ = 'ticket_attachments'

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey('support_tickets.id'), nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    storage_path = Column(String, nullable=False)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship('SupportTicket', back_populates='attachments')
    uploader = relationship('User')
