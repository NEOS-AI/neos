from pathlib import Path


def test_bitemporal_evidence_migration_adds_validity_columns():
    sql = Path("db/migrations/034_add_bitemporal_evidence_claims.sql").read_text()

    assert "valid_from TIMESTAMPTZ" in sql
    assert "valid_to TIMESTAMPTZ" in sql
    assert "replaced_by_claim_id INT" in sql
    assert "idx_evidence_claims_current_valid" in sql
