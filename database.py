from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import inspect, text
import os

db = SQLAlchemy()
migrate = Migrate()

def init_db(app):
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///auralis.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    migrate.init_app(app, db)


def ensure_database_schema(app):
    """
    Development-safe schema sync for SQLite.
    - Creates missing tables from SQLAlchemy metadata.
    - Adds missing columns for existing tables (best-effort, non-destructive).
    """
    with app.app_context():
        db.create_all()

        engine = db.engine
        if engine.url.get_backend_name() != "sqlite":
            return

        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        for table_name, table in db.metadata.tables.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                column_type_sql = column.type.compile(dialect=engine.dialect)
                add_sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {column_type_sql}'

                # SQLite cannot add NOT NULL column without a default; keep this additive-only.
                with engine.begin() as conn:
                    conn.execute(text(add_sql))
