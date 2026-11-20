"""Exercise migrations 001 and 002 on real PostgreSQL in an ephemeral cluster.

From the repository root, with a local Docker engine:
    python backend/tests/postgres/verify_publication.py

Requires Python 3.10+. No existing database URL is accepted or used.
"""

import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path


HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE.parents[1] / "migrations"
ENV = {k: v for k, v in os.environ.items() if not k.upper().startswith("PG")}
ENV["PGCLIENTENCODING"] = "UTF8"


def execute(args, *, sql=None, check=True, timeout=45):
    result = subprocess.run(args, input=sql, env=ENV, text=True, encoding="utf-8",
                            capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def wait_for(condition, description, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {description}")


@contextmanager
def disposable():
    name = "inkloom_qa_" + uuid.uuid4().hex
    options = ["-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "postgres"]
    # Explicit local socket/pipe; ignore any user-selected remote context.
    engine = ("npipe:////./pipe/dockerDesktopLinuxEngine" if os.name == "nt"
              else "unix:///var/run/docker.sock")
    docker = ["docker", "--host", engine]
    execute([*docker, "run", "--rm", "--detach", "--network", "none", "--name", name,
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "pgvector/pgvector:pg16"], timeout=300)
    try:
        client = [*docker, "exec", "-i", name, "psql", "-h", "127.0.0.1", *options]
        wait_for(lambda: execute(client, sql="SELECT 1;", check=False).returncode == 0,
                 "isolated container database")
        yield client
    finally:
        execute([*docker, "rm", "--force", "--volumes", name])


def publication(text, source=None, revision=None, version="1.0", bad_chunk=False, org="qa-org"):
    # Inputs are constants from this test or UUIDs previously returned by postgres.
    source_sql = f"'{uuid.UUID(source)}'" if source else "NULL"
    chunks = [dict(content=text, page_number=1, section="Rules", chunk_index=0, embedding=[1, 2, 3])]
    if bad_chunk:
        chunks.append(dict(chunks[0], chunk_index=1, embedding=[1, 2]))
    payload = json.dumps(chunks).replace("'", "''")
    return f"""SELECT new_document_id FROM publish_brand_document_version_v2(
        {source_sql}, {int(revision) if revision is not None else 'NULL'}, 'Synthetic Rules',
        'guideline', '{version}', 'synthetic.txt', 'synthetic', '{org}', 'Test Manager',
        'Synthetic publication test', '{payload}'::jsonb);"""


def run(client):
    def query(sql):
        return execute(client, sql=sql).stdout.strip()

    def expect(sql, expected):
        actual = query(sql)
        if actual != expected:
            raise AssertionError(f"{sql}: expected {expected!r}, received {actual!r}")

    def reject(sql, message):
        result = execute(client, sql=sql, check=False)
        if not result.returncode or message not in result.stderr:
            raise AssertionError(f"Expected {message!r}; got {result.returncode}, {result.stderr!r}")

    query((HERE / "publication_fixture.sql").read_text(encoding="utf-8"))
    for name in ["001_atomic_brand_publication.sql", "002_atomic_brand_chunks.sql"]:
        query((MIGRATIONS / name).read_text(encoding="utf-8"))
        print("PASS", name, flush=True)

    first = query("SET ROLE service_role; " + publication("Original"))
    expect("SELECT org_id,document_family,revision_number,is_active FROM brand_documents",
           "qa-org|synthetic rules::guideline|1|t")
    second = query(publication("Replacement", first, 1, "1.1"))
    expect(f"SELECT previous_version_id FROM brand_documents WHERE id='{second}'", first)
    expect("SELECT string_agg(action, ',' ORDER BY action) FROM brand_document_audit",
           "deactivated,published,published")
    print("PASS first upload and replacement", flush=True)

    reject(publication("Roll back", second, 2, "1.2", bad_chunk=True), "dimensions")
    expect("SELECT count(*) FROM brand_document_audit", "3")
    expect("SELECT count(*) FROM brand_chunks", "2")
    expect("SELECT count(*) FROM brand_documents", "2")
    expect("SELECT id FROM brand_documents WHERE is_active", second)
    expect(f"SELECT content FROM brand_chunks WHERE document_id='{second}'", "Replacement")
    print("PASS second chunk rejected, prior version/content/audit intact", flush=True)

    # Hold one successful publication uncommitted until the competitor is
    # observed waiting on its advisory lock. This guarantees an actual overlap.
    holder = subprocess.Popen(client, env=ENV, text=True, encoding="utf-8", stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        holder.stdin.write("SET application_name='qa_holder'; BEGIN;\n"
                           + publication("Winning correction", second, 2, "1.2") + "\n")
        holder.stdin.flush()
        wait_for(lambda: query("SELECT count(*) FROM pg_stat_activity WHERE application_name='qa_holder'"
                               " AND state='idle in transaction' AND query LIKE '%publish_brand_document_version_v2%'") == "1",
                 "first publication holding its transaction")
        with ThreadPoolExecutor(max_workers=1) as pool:
            rival = pool.submit(reject, "SET application_name='qa_rival';\n"
                                + publication("Competing correction", second, 2, "1.2"), "STALE_VERSION")
            try:
                wait_for(lambda: query("SELECT count(*) FROM pg_stat_activity WHERE application_name='qa_rival'"
                                       " AND wait_event_type='Lock' AND wait_event='advisory'") == "1",
                         "second publication blocked on the same family")
            finally:
                out, err = holder.communicate("COMMIT;\n", timeout=15)
            if holder.returncode:
                raise RuntimeError(err)
            winner = str(uuid.UUID(out.strip()))
            rival.result()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate()
    reject(publication("Stale rectification", second, 2, "1.2"), "STALE_VERSION")
    expect("SELECT id FROM brand_documents WHERE is_active", winner)
    expect("SELECT count(*) FROM detect_ambiguous_active_brand_documents()", "0")
    expect("SELECT revision_number,is_active,content FROM brand_documents d JOIN brand_chunks c "
           "ON c.document_id=d.id ORDER BY revision_number", "1|f|Original\n2|f|Replacement\n3|t|Winning correction")
    expect(f"SELECT previous_version_id FROM brand_documents WHERE id='{winner}'", second)
    expect("SELECT count(*) FROM brand_document_audit", "5")
    independently_active = query(publication("Other organisation", org="qa-other"))
    expect("SELECT id FROM brand_documents WHERE org_id='qa-org' AND is_active", winner)
    expect("SELECT id FROM brand_documents WHERE org_id='qa-other' AND is_active", independently_active)
    expect("SELECT count(*) FROM detect_ambiguous_active_brand_documents()", "0")
    print("PASS independent family for the same title in another organisation", flush=True)
    print("PASS overlapping publications, stale approval, single active revision, preserved history", flush=True)


if __name__ == "__main__":
    with disposable() as session:
        run(session)
    with disposable() as session:
        execute(session, sql=(HERE / "publication_fixture.sql").read_text(encoding="utf-8"))
        execute(session, sql="""
            INSERT INTO brand_documents(id,title,category,version,is_active,source_filename,storage_path)
            VALUES ('00000000-0000-4000-8000-000000000001','Legacy','guideline','1.0',false,'qa.txt','org:qa-old|brand:QA|prev:|'),
                   ('00000000-0000-4000-8000-000000000002','Legacy','guideline','1.1',true,'qa.txt','org:qa-old|brand:QA|prev:00000000-0000-4000-8000-000000000001|'),
                   ('00000000-0000-4000-8000-000000000003','Newer','guideline','1.0',false,'qa.txt','__org=qa-new|'),
                   ('00000000-0000-4000-8000-000000000004','Newer','guideline','1.1',true,'qa.txt','__org=qa-new|__prev=00000000-0000-4000-8000-000000000003|');
        """)
        for name in ["001_atomic_brand_publication.sql", "002_atomic_brand_chunks.sql"]:
            execute(session, sql=(MIGRATIONS / name).read_text(encoding="utf-8"))
        result = execute(session, sql="SELECT org_id,coalesce(previous_version_id::text,'none'),revision_number,is_active FROM brand_documents ORDER BY id;").stdout.strip()
        expected = ("qa-old|none|1|f\nqa-old|00000000-0000-4000-8000-000000000001|2|t\n"
                    "qa-new|none|1|f\nqa-new|00000000-0000-4000-8000-000000000003|2|t")
        if result != expected:
            raise AssertionError(f"Legacy metadata history mismatch: {result!r}")
        print("PASS legacy and newer metadata backfill and history", flush=True)
