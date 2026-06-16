"""Database layer for the JavaAPEX platform.

Provides:
- connection: PostgreSQL connection pool helpers
- models:   Pydantic models mirroring apex schema tables
- service:  CRUD functions for all 10 tables
- router:   FastAPI REST router exposing all CRUD operations
"""