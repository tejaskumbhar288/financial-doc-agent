"""Initial schema: vendors, documents, anomaly_flags

Revision ID: 001
Revises:
Create Date: 2025-08-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create vendors table
    op.create_table(
        'vendors',
        sa.Column('vendor_name', sa.String(255), nullable=False),
        sa.Column('banking_fingerprints', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('z_score_mean', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('z_score_stddev', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('invoice_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False, onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('vendor_name')
    )

    # Create extracted_documents table
    op.create_table(
        'extracted_documents',
        sa.Column('document_id', sa.String(64), nullable=False),
        sa.Column('source_filename', sa.String(255), nullable=False),
        sa.Column('document_type', sa.Enum('RECEIPT', 'INVOICE', 'STATEMENT', name='documenttype'), nullable=False),
        sa.Column('vendor_name', sa.String(255), nullable=True),
        sa.Column('extracted_data', sa.JSON(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(precision=3, scale=2), nullable=False, server_default='0.0'),
        sa.Column('status', sa.Enum('PROCESSED', 'NEEDS_REVIEW', 'QUARANTINED', 'UNRECONCILED', name='processingstatus'), nullable=False, server_default='PROCESSED'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False, onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['vendor_name'], ['vendors.vendor_name'], ),
        sa.PrimaryKeyConstraint('document_id')
    )

    # Create anomaly_flags table
    op.create_table(
        'anomaly_flags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.String(64), nullable=False),
        sa.Column('rule_name', sa.String(64), nullable=False),
        sa.Column('severity', sa.Enum('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', name='anomalyseverity'), nullable=False),
        sa.Column('description', sa.String(512), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['extracted_documents.document_id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('anomaly_flags')
    op.drop_table('extracted_documents')
    op.drop_table('vendors')
