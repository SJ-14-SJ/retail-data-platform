from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    Text,
    ForeignKey,
    event,
)
from sqlalchemy.engine import Engine

metadata = MetaData()
raw_events = Table(
    "raw_events",
    metadata,
    Column("event_id", String(100), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("outcome", String(30), nullable=False),
    Column("reason", Text),
)
products = Table("products", metadata, Column("sku", String(100), primary_key=True))
customers = Table(
    "customers", metadata, Column("customer_id", String(100), primary_key=True)
)
order_lines = Table(
    "order_lines",
    metadata,
    Column("line_id", String(100), primary_key=True),
    Column("order_id", String(100), nullable=False),
    Column("sku", String(100), ForeignKey("products.sku"), nullable=False),
    Column(
        "customer_id", String(100), ForeignKey("customers.customer_id"), nullable=False
    ),
    Column("order_date", String(10), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price_cents", Integer, nullable=False),
    Column("status", String(20), nullable=False),
    Column("revision", Integer, nullable=False),
)
checkpoints = Table(
    "checkpoints",
    metadata,
    Column("source", String(300), primary_key=True),
    Column("offset", Integer, nullable=False),
)


def connect(url: str) -> Engine:
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    return engine
