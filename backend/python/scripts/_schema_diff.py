"""RDS 실제 스키마 vs init_v2.sql 비교 — 고아 extra 컬럼 전수 조사."""
import os, re, pymysql
from pathlib import Path

env_path = Path(__file__).resolve().parents[3] / '.env'
for line in env_path.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    os.environ[k.strip()] = v.strip()

# ── 1. init_v2.sql 파싱 (테이블별 허용 컬럼 set) ──
sql_path = Path(__file__).resolve().parents[3] / 'db' / 'init_v2.sql'
sql_text = sql_path.read_text(encoding='utf-8')

expected: dict[str, set[str]] = {}
# CREATE TABLE xxx ( ... );
for m in re.finditer(r"CREATE TABLE\s+(\w+)\s*\((.*?)\)\s*ENGINE", sql_text, re.DOTALL | re.IGNORECASE):
    table = m.group(1)
    body = m.group(2)
    cols = set()
    for line in body.splitlines():
        line = line.strip().rstrip(',')
        if not line:
            continue
        if line.upper().startswith(('FOREIGN KEY', 'PRIMARY KEY', 'UNIQUE KEY', 'INDEX', 'KEY ', 'CONSTRAINT', 'CHECK')):
            continue
        first = line.split()[0].strip('`')
        if first and first.lower() not in ('primary', 'foreign', 'unique', 'index', 'key', 'constraint', 'check'):
            cols.add(first)
    expected[table] = cols

# ── 2. RDS 실제 컬럼 ──
conn = pymysql.connect(
    host=os.environ['DB_HOST'], port=int(os.environ.get('DB_PORT', '3306')),
    user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
    database=os.environ['DB_NAME'], charset='utf8mb4', connect_timeout=5
)
cur = conn.cursor(pymysql.cursors.DictCursor)

cur.execute("SHOW TABLES")
actual_tables = [list(r.values())[0] for r in cur.fetchall()]

print("=" * 80)
print("Schema Drift Report: RDS vs init_v2.sql")
print("=" * 80)

any_drift = False
for tb in sorted(actual_tables):
    cur.execute(f"DESCRIBE {tb}")
    actual_cols = {r['Field']: r for r in cur.fetchall()}
    exp = expected.get(tb)

    if exp is None:
        print(f"\n⚠️  [{tb}] init_v2.sql 에 없는 테이블 (RDS only)")
        any_drift = True
        continue

    extra = set(actual_cols) - exp
    missing = exp - set(actual_cols)
    if not extra and not missing:
        continue
    any_drift = True
    print(f"\n▶ {tb}")
    for c in sorted(extra):
        info = actual_cols[c]
        null_str = 'NULL' if info['Null'] == 'YES' else 'NOT NULL'
        def_str = f" DEF={info['Default']}" if info['Default'] is not None else ''
        risk = ' 🚨' if info['Null'] == 'NO' and info['Default'] is None else ''
        print(f"    [EXTRA]   {c:25} {info['Type']:30} {null_str}{def_str}{risk}")
    for c in sorted(missing):
        print(f"    [MISSING] {c}")

# init_v2.sql 에만 있는 테이블
only_in_sql = set(expected) - set(actual_tables)
for tb in sorted(only_in_sql):
    print(f"\n❌ [{tb}] init_v2.sql 정의됐지만 RDS 에 없음")
    any_drift = True

print("\n" + "=" * 80)
print("정상" if not any_drift else "⚠️  Drift 발견 — 🚨 는 NOT NULL + DEFAULT 없음 (INSERT 시 즉시 실패)")
print("=" * 80)

conn.close()
