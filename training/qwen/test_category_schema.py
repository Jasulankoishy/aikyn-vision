"""CPU-only consistency between published checklist and category requirements."""
from native_core import FIELDS, RISK_KEYS
from result_quality import REQUIREMENTS


def test_all_fourteen_compound_categories_are_explicit_checklist_risks():
    assert set(REQUIREMENTS) == {f'c{index:02}' for index in range(1, 15)}
    primary = {values[0] for values in REQUIREMENTS.values()}
    assert len(primary) == 14
    assert primary == set(RISK_KEYS)
    assert all(key in FIELDS for keys in REQUIREMENTS.values() for key in keys)


def test_absence_sensitive_categories_use_positive_compound_keys():
    assert REQUIREMENTS['c03'] == ('cash_receipt_without_visible_count',)
    assert REQUIREMENTS['c04'] == ('cash_receipt_without_visible_identity_check',)
    assert 'cash_counted' not in REQUIREMENTS['c03']
    assert 'document_checked' not in REQUIREMENTS['c04']
