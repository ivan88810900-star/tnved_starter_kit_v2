"""
Конфигурация pytest с фикстурами
"""
import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import get_db, Base
from app.models import HSCode, Note, TariffRate, NTMMeasure, DataSource

# Тестовая база данных в памяти
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="function")
def client():
    """Тестовый клиент FastAPI"""
    # Создаем таблицы для каждого теста
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    # Очищаем таблицы после теста
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def db_session():
    """Тестовая сессия базы данных"""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def sample_hs_codes(db_session):
    """Фикстура с тестовыми кодами ТН ВЭД"""
    codes = [
        HSCode(
            code="7009.10.0009",
            title_ru="Зеркала из стекла, необработанные",
            title_en="Glass mirrors, unworked",
            chapter="70",
            heading="7009",
            subheading="7009.10.0009"
        ),
        HSCode(
            code="4016.99.0000",
            title_ru="Изделия из резины прочие",
            title_en="Other articles of rubber",
            chapter="40",
            heading="4016",
            subheading="4016.99.0000"
        ),
        HSCode(
            code="8517.12.0000",
            title_ru="Телефоны мобильные",
            title_en="Mobile telephones",
            chapter="85",
            heading="8517",
            subheading="8517.12.0000"
        ),
        HSCode(
            code="6203.42.3100",
            title_ru="Костюмы мужские из хлопка",
            title_en="Men's suits of cotton",
            chapter="62",
            heading="6203",
            subheading="6203.42.3100"
        ),
        HSCode(
            code="8703.23.1000",
            title_ru="Автомобили легковые с двигателем объемом 1500-3000 см³",
            title_en="Motor cars with engine capacity 1500-3000 cm³",
            chapter="87",
            heading="8703",
            subheading="8703.23.1000"
        )
    ]
    
    for code in codes:
        db_session.add(code)
    db_session.commit()
    
    return codes

@pytest.fixture
def sample_notes(db_session):
    """Фикстура с тестовыми примечаниями"""
    notes = [
        Note(
            level="section",
            ref_id="I",
            text="Примечания к разделу I: Живые животные и продукты животного происхождения"
        ),
        Note(
            level="chapter",
            ref_id="70",
            text="Примечания к группе 70: Стекло и изделия из него"
        ),
        Note(
            level="chapter",
            ref_id="40",
            text="Примечания к группе 40: Каучук, резина и изделия из них"
        )
    ]
    
    for note in notes:
        db_session.add(note)
    db_session.commit()
    
    return notes

@pytest.fixture
def sample_tariff_rates(db_session):
    """Фикстура с тестовыми тарифными ставками"""
    rates = [
        TariffRate(
            hs_code="7009.10.0009",
            duty="5%",
            vat="20%",
            add="0%",
            source_version="2024.01"
        ),
        TariffRate(
            hs_code="4016.99.0000",
            duty="6.5%",
            vat="20%",
            add="0%",
            source_version="2024.01"
        ),
        TariffRate(
            hs_code="8517.12.0000",
            duty="0%",
            vat="20%",
            add="0%",
            source_version="2024.01"
        )
    ]
    
    for rate in rates:
        db_session.add(rate)
    db_session.commit()
    
    return rates

@pytest.fixture
def sample_ntm_measures(db_session):
    """Фикстура с тестовыми нетарифными мерами"""
    measures = [
        NTMMeasure(
            hs_code_prefix="70",
            title="Сертификация стеклянных изделий",
            basis="ТР ТС 004/2011",
            country="РФ",
            notes="Требуется сертификат соответствия"
        ),
        NTMMeasure(
            hs_code_prefix="40",
            title="Экологическая экспертиза резиновых изделий",
            basis="ФЗ-7",
            country="РФ",
            notes="Для изделий из синтетического каучука"
        )
    ]
    
    for measure in measures:
        db_session.add(measure)
    db_session.commit()
    
    return measures

@pytest.fixture
def sample_data_sources(db_session):
    """Фикстура с тестовыми источниками данных"""
    sources = [
        DataSource(
            key="tnved_tree",
            version="2024.01",
            authority="ЕЭК",
            url="https://example.com/tnved",
            checksum="abc123",
        ),
        DataSource(
            key="tariff_rates",
            version="2024.01",
            authority="ФТС",
            url="https://example.com/tariff",
            checksum="def456",
        )
    ]
    
    for source in sources:
        db_session.add(source)
    db_session.commit()
    
    return sources

@pytest.fixture
def temp_excel_file():
    """Фикстура с временным Excel файлом для тестирования batch"""
    import pandas as pd
    import tempfile
    
    # Создаем тестовые данные
    data = {
        'ID': [1, 2, 3],
        'Описание': [
            'Зеркало настенное из стекла',
            'Резиновые перчатки медицинские',
            'Мобильный телефон iPhone'
        ],
        'Характеристики': [
            'Размер 50x70 см, без рамы',
            'Одноразовые, латексные',
            '128 ГБ, черный цвет'
        ]
    }
    
    df = pd.DataFrame(data)
    
    # Создаем временный файл
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        yield tmp_file.name
    
    # Удаляем файл после теста
    os.unlink(tmp_file.name)

@pytest.fixture(autouse=True)
def setup_test_env():
    """Настройка тестового окружения"""
    # Устанавливаем тестовые переменные окружения
    os.environ["DB_URL"] = "sqlite:///./test.db"
    os.environ["AI_OFFLINE_MODE"] = "false"
    os.environ["ALLOW_EXTERNAL_AI"] = "true"
    os.environ["AUDIT_LOGGING"] = "false"
    os.environ["ADMIN_API_KEY"] = "test-admin-key"
    
    yield
    
    # Очищаем переменные окружения после теста
    test_vars = ["DB_URL", "AI_OFFLINE_MODE", "ALLOW_EXTERNAL_AI", "AUDIT_LOGGING", "ADMIN_API_KEY"]
    for var in test_vars:
        if var in os.environ:
            del os.environ[var]
















