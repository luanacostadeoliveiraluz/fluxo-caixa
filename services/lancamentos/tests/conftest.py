import pytest

from app.db import Database
from app.repository import criar_schema


@pytest.fixture
def db(tmp_path):
    banco = Database(f"sqlite:///{tmp_path / 'teste.db'}")
    criar_schema(banco)
    yield banco
    banco.close()
