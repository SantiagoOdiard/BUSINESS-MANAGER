"""Add Plant and UserPlantAccess models

Revision ID: add_plant_models
Revises: 
Create Date: 2026-05-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_plant_models'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create Plant table
    op.create_table(
        'plants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_plants_id'), 'plants', ['id'], unique=True)
    
    # Create UserPlantAccess table
    op.create_table(
        'user_plant_access',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('plant_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plant_id'], ['plants.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_plant_access_id'), 'user_plant_access', ['id'], unique=True)
    
    # Add phone_number to Employee table
    op.add_column('employees', sa.Column('phone_number', sa.String(), nullable=True))
    
    # Add plant_id to SupportTicket table
    op.add_column('support_tickets', sa.Column('plant_id', sa.Integer(), nullable=False, server_default='1'))
    op.create_foreign_key('fk_support_tickets_plant_id', 'support_tickets', 'plants', ['plant_id'], ['id'])


def downgrade():
    # Drop foreign key from support_tickets
    op.drop_constraint('fk_support_tickets_plant_id', 'support_tickets', type_='foreignkey')
    
    # Drop plant_id column from support_tickets
    op.drop_column('support_tickets', 'plant_id')
    
    # Drop phone_number column from employees
    op.drop_column('employees', 'phone_number')
    
    # Drop UserPlantAccess table
    op.drop_index(op.f('ix_user_plant_access_id'), table_name='user_plant_access')
    op.drop_table('user_plant_access')
    
    # Drop Plant table
    op.drop_index(op.f('ix_plants_id'), table_name='plants')
    op.drop_table('plants')
