from pathlib import Path


def test_all_raw_tables_have_daily_partition_ttl() -> None:
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0001_initial.py"
    content = migration.read_text(encoding="utf-8")
    assert ") PARTITION BY RANGE(collected_at);" in content
    assert "public.sample_batches" in content
    assert "public.gpu_samples" in content
    assert "retention = '30 days'" in content
    assert "retention_keep_table = false" in content
    assert "token varchar(100) NOT NULL" in content
    assert "token_ciphertext" not in content
