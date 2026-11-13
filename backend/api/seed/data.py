"""Describe fictitious release inventory, never deployment credentials."""
PORTFOLIOS = (
    {'name': 'Payments', 'ownerName': 'Demo Payments Leader', 'description': 'Fictitious payment processing inventory', 'productArea': 'Payments', 'status': 'Active'},
    {'name': 'Customer Platform', 'ownerName': 'Demo Customer Leader', 'description': 'Fictitious customer service inventory', 'productArea': 'Customer', 'status': 'Active'},
    {'name': 'Data & Analytics', 'ownerName': 'Demo Data Leader', 'description': 'Fictitious reporting and analytics inventory', 'productArea': 'Data', 'status': 'Active'},
)
# name, parent position, quality, health, automation, unit coverage, defects,
# critical defects, risk, criticality, tier, lifecycle, stack
APPLICATIONS = (
    ('Payment Gateway', 0, 92, 94, 88, 90, 3, 0, 'Low', 'Critical', 1, 'Active', 'Python, PostgreSQL'),
    ('Settlement Engine', 0, 68, 72, 55, 63, 18, 3, 'High', 'Critical', 1, 'Active', 'Java, Kafka'),
    ('Fraud Review', 0, 81, 83, 72, 80, 8, 1, 'Medium', 'High', 2, 'Active', 'React, Python'),
    ('Legacy Billing', 0, 45, 50, 20, 30, 27, 5, 'High', 'Medium', 3, 'Deprecated', 'Java'),
    ('Customer Portal', 1, 89, 91, 84, 87, 5, 0, 'Low', 'High', 2, 'Active', 'React, FastAPI'),
    ('Identity Directory', 1, 77, 79, 65, 74, 10, 1, 'Medium', 'Critical', 1, 'Active', 'Java, MongoDB'),
    ('Contact Archive', 1, 60, 65, 35, 48, 12, 0, 'Medium', 'Low', 4, 'Retired', 'Python'),
    ('Analytics Lake', 2, 85, 87, 79, 82, 7, 0, 'Low', 'High', 2, 'Active', 'Python, Spark'),
    ('Executive Reporting', 2, 73, 76, 61, 69, 14, 2, 'High', 'Medium', 3, 'Active', 'React, Python'),
    ('Data Catalog', 2, 95, 96, 92, 94, 1, 0, 'Low', 'Low', 4, 'Active', 'Python, MongoDB'),
)
# Empty access for enterprise roles intentionally means unrestricted in existing policy.
USERS = (
    ('Administrator', 'admin', 'Demo Administrator', ()),
    ('Executive', 'executive', 'Demo Executive', ()),
    ('Portfolio Leader', 'portfolio-leader', 'Demo Portfolio Leader', (0, 1)),
    ('Engineer', 'engineer', 'Demo Engineer', (0,)),
    ('Auditor', 'auditor', 'Demo Auditor', ()),
    ('Read Only', 'read-only', 'Demo Read Only', (2,)),
)


def application_payload(row: tuple, portfolio_id: str) -> dict:
    """Build every required inventory field for strict domain validation."""
    name, parent, quality, health, automation, unit, defects, critical, risk, criticality, tier, lifecycle, stack = row
    return dict(name=name, description=f'Fictitious release demonstration: {name}', portfolioId=portfolio_id,
                productArea=PORTFOLIOS[parent]['productArea'], businessOwner='Demo Business Owner',
                technologyOwner='Demo Technology Owner', etsOwner='Demo ETS Owner', criticality=criticality,
                tier=tier, lifecycleStatus=lifecycle, technologyStack=stack, repositoryUrl=None, pipelineUrl=None,
                applicationHealthScore=health, qualityScore=quality, automationCoverage=automation,
                unitTestCoverage=unit, openDefects=defects, openCriticalDefects=critical, riskLevel=risk)
