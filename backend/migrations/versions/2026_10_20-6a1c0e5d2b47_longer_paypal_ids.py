"""longer paypal ids

Log in with PayPal's user id is 43 characters; the column held 40, which Postgres rejected.

Revision ID: 6a1c0e5d2b47
Revises: 202f9b907f34
Create Date: 2026-10-20 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a1c0e5d2b47'
down_revision: Union[str, Sequence[str], None] = '202f9b907f34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('paypal_links', schema=None) as batch_op:
        batch_op.alter_column('payer_id', existing_type=sa.String(length=40), type_=sa.String(length=100), existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('paypal_links', schema=None) as batch_op:
        batch_op.alter_column('payer_id', existing_type=sa.String(length=100), type_=sa.String(length=40), existing_nullable=False)
