"""Update AppWorld's downloaded data for the policy APIs.

Run once after `appworld download data`, and again whenever an API changes. Safe to re-run.

1. Add the (empty) policy tables to data/base_dbs/supervisor.db. Tasks load base DBs without creating
   tables, so the tables must exist there; each task then inserts its own policies.
2. Regenerate the API docs files (data/api_docs/<format>/<app>.json) from the code, with AppWorld's
   generate/code/api_docs.py. Existing APIs keep their order; new APIs are added at the end.
3. Sync the API docs DB (data/base_dbs/api_docs.db), which agents read through apis.api_docs, with the code:
   rows are updated in place (keeping their ids and order), new APIs are added at the end, and APIs that
   no longer exist are removed.

Regenerating also fixes docs that were out of date in the download: e.g., the 6 "download receipt" APIs
list file_system_access_token as optional, but the APIs require it.

Usage (from the repo root): .venv/bin/python scripts/prepare_policy_data.py
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from appworld.api_docs import prepare_api_docs
from appworld.apps import get_all_apps

ROOT = Path(__file__).resolve().parents[1]
BASE_DBS = ROOT / "data" / "base_dbs"


def add_policy_tables() -> None:
    from appworld.apps.supervisor import models as supervisor_models

    engine = create_engine(f"sqlite:///{BASE_DBS / 'supervisor.db'}")
    supervisor_models.SQLModel.metadata.create_all(engine)  # creates only the missing tables
    tables = inspect(engine).get_table_names()
    engine.dispose()
    assert {"person_policies", "app_policies"} <= set(tables), tables
    print(f"supervisor.db tables: {', '.join(sorted(tables))}")


def regenerate_api_docs_files() -> None:
    print("Regenerating data/api_docs ...")
    # The tool calls every API once to check it is reachable; hide FastAPI's deprecation warning from that.
    env = os.environ | {"PYTHONWARNINGS": "ignore:ORJSONResponse is deprecated"}
    command = [sys.executable, "-m", "generate.code.api_docs", "--silent"]
    subprocess.run(command, cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)


def sync_api_docs_db() -> None:
    from appworld.apps.api_docs import models as api_docs_models

    api_docs_models.SQLModel.set_db(str(BASE_DBS))  # works directly on the file on disk
    ApiDoc = api_docs_models.ApiDoc
    old_records = {(record.app_name_, record.api_name): record for record in ApiDoc.all()}
    added, updated = [], []
    for app_name in get_all_apps(skip_admin=True, skip_api_docs=False, skip_supervisor=False):
        for doc in prepare_api_docs(app_name):
            fields = {k: v for k, v in doc.items() if k != "app_name"} | {"app_name_": app_name}
            record = old_records.pop((app_name, doc["api_name"]), None)
            if record is None:
                added.append(ApiDoc.create_save(**fields))
                continue
            if any(getattr(record, key) != value for key, value in fields.items()):
                for key, value in fields.items():
                    setattr(record, key, value)
                record.save()
                updated.append(record)
    for record in old_records.values():
        record.delete()
    print(f"api_docs.db: {len(ApiDoc.all())} APIs; added {len(added)}, updated {len(updated)}, "
          f"removed {len(old_records)}")
    for record in updated:
        print(f"  updated: {record.app_name_}.{record.api_name}")
    api_docs_models.SQLModel.db.engine.dispose()


def main() -> None:
    os.chdir(ROOT)
    add_policy_tables()
    regenerate_api_docs_files()
    sync_api_docs_db()
    print("Done.")


if __name__ == "__main__":
    main()
