"""Exercise seed configuration and coherent full-schema inventory."""
import secrets
import pytest
from bson import ObjectId
from api.core.config import Settings
from api.seed.data import PORTFOLIOS, APPLICATIONS, USERS, application_payload
from api.domains.applications.schemas import ApplicationCreate
from api.domains.portfolios.schemas import PortfolioCreate
from api.core.policy import ROLE_MAXIMUM


def configuration(**changes):
    """Supply generated test-only credentials and no inherited env file."""
    return Settings(_env_file=None, MONGODB_URI='mongodb://127.0.0.1:27017', MONGODB_DB='etsip_test_seed',
                    JWT_SECRET=secrets.token_urlsafe(48), **changes)


@pytest.mark.parametrize('key', ['SEED_ADMIN_PASSWORD', 'SEED_DEMO_PASSWORD'])
@pytest.mark.parametrize('value', [None, '', '   ', 'dummy-replace-me', 'change-in-production', 'password', 'x' * 73, 'é' * 37, 'invalid\0credential'])
def test_invalid_secret_is_rejected_without_disclosing_input(key, value):
    """Fail safely for absent, sample and bcrypt-truncated seed inputs."""
    values = dict(SEED_ADMIN_PASSWORD=secrets.token_urlsafe(24), SEED_DEMO_PASSWORD=secrets.token_urlsafe(24))
    values[key] = value
    with pytest.raises(ValueError, match=key) as error:
        configuration(**values).require_seed_passwords()
    if value and value.strip():
        assert value not in str(error.value)


def test_optional_seed_disabled_and_explicit_credentials_roundtrip():
    """Leave normal startup independent of seeding and accept secure input unchanged."""
    settings = configuration()
    assert not settings.SEED_ON_STARTUP
    admin, demo = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    settings = configuration(SEED_ADMIN_PASSWORD=admin, SEED_DEMO_PASSWORD=demo)
    assert settings.require_seed_passwords() == (admin, demo)
    assert admin not in repr(settings) and demo not in repr(settings)


def test_dataset_is_unique_linked_diverse_and_validates_full_schemas():
    """Verify all authored records match existing closed domain contracts."""
    assert len(PORTFOLIOS) == 3 and len(APPLICATIONS) == 10
    assert len({row[0] for row in APPLICATIONS}) == 10
    assert {row[0] for row in USERS} == set(ROLE_MAXIMUM)
    assert len({row[1] for row in USERS}) == 6
    for portfolio in PORTFOLIOS:
        PortfolioCreate.model_validate(portfolio)
        assert 'qualityScore' not in portfolio
    records = [ApplicationCreate.model_validate(application_payload(row, str(ObjectId()))) for row in APPLICATIONS]
    assert {record.riskLevel for record in records} == {'Low', 'Medium', 'High'}
    assert {record.lifecycleStatus for record in records} == {'Active', 'Deprecated', 'Retired'}
    assert len({record.qualityScore for record in records}) > 5
    assert {row[1] for row in APPLICATIONS} == {0, 1, 2}
