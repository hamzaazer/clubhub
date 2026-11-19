"""Copy this app's SQLite data into an empty Supabase PostgreSQL database."""

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import db
from app import models  # noqa: F401 - registers the models on db.metadata


def table_counts(engine, table_names):
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    counts = {}
    for name in table_names:
        if name in present:
            with engine.connect() as connection:
                counts[name] = connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "instance/club.db",
                        help="SQLite database file (default: instance/club.db)")
    parser.add_argument("--apply", action="store_true", help="Create the schema and import the rows")
    args = parser.parse_args()

    target_url = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    if not target_url:
        parser.error("set SUPABASE_DATABASE_URL to the Supabase session-pooler connection string")
    url = make_url(target_url)
    if url.get_backend_name() != "postgresql":
        parser.error("SUPABASE_DATABASE_URL must be a PostgreSQL connection string")
    if not args.source.is_file():
        parser.error(f"SQLite source file not found: {args.source}")

    source = create_engine(URL.create("sqlite", database=str(args.source.resolve())))
    target = create_engine(target_url, pool_pre_ping=True)
    app_tables = [table.name for table in db.metadata.sorted_tables]

    # Verify the source is readable and fail before creating any destination objects.
    source_inspector = inspect(source)
    source_tables = set(source_inspector.get_table_names())
    selected_tables = [name for name in app_tables if name in source_tables]
    if not selected_tables:
        parser.error("the SQLite file does not contain any ClubHub tables")
    source_counts = table_counts(source, selected_tables)

    with target.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    target_counts = table_counts(target, app_tables)
    populated = {name: count for name, count in target_counts.items() if count}
    if populated:
        raise SystemExit("Refusing to import into a non-empty ClubHub database: " +
                         ", ".join(f"{name}={count}" for name, count in populated.items()))

    print(f"Source: {args.source.resolve()}")
    print("Supabase connection: reachable (credentials not displayed)")
    for name in selected_tables:
        print(f"  {name}: {source_counts[name]} rows")
    if not args.apply:
        print("Dry run only. Review the counts, then rerun with --apply to import.")
        return

    answer = input("Type IMPORT to create the app schema and copy this dataset to Supabase: ")
    if answer != "IMPORT":
        raise SystemExit("Import cancelled.")

    db.metadata.create_all(target)
    preparer = target.dialect.identifier_preparer
    with target.begin() as connection:
        for table in db.metadata.sorted_tables:
            quoted_name = preparer.quote(table.name)
            connection.exec_driver_sql(f"ALTER TABLE public.{quoted_name} ENABLE ROW LEVEL SECURITY")
    with target.begin() as destination, source.connect() as origin:
        for name in app_tables:
            if name not in source_tables:
                continue
            destination_table = db.metadata.tables[name]
            source_metadata = MetaData()
            source_table = source_metadata.reflect(origin, only=[name]).tables[name]
            common_columns = [column.name for column in destination_table.columns
                              if column.name in source_table.columns]
            result = origin.execute(select(source_table))
            copied = 0
            while rows := result.fetchmany(500):
                values = [{column: row._mapping[column] for column in common_columns} for row in rows]
                if values:
                    destination.execute(destination_table.insert(), values)
                    copied += len(values)
            print(f"  imported {name}: {copied} rows")

            if "id" in destination_table.columns and target.dialect.name == "postgresql":
                max_id = destination.scalar(select(func.max(destination_table.c.id)))
                if max_id is not None:
                    sequence = destination.scalar(select(func.pg_get_serial_sequence(
                        f"public.{name}", "id")))
                    if sequence:
                        destination.execute(select(func.setval(sequence, max_id, True)))

    # Match the app's startup role import for legacy databases with member titles.
    if "users" in source_tables and "club_roles" in app_tables:
        with target.begin() as connection:
            connection.execute(text(
                "INSERT INTO public.club_roles (name) "
                "SELECT DISTINCT trim(member_title) FROM public.users "
                "WHERE trim(coalesce(member_title, '')) <> '' "
                "AND lower(trim(member_title)) NOT IN (SELECT lower(name) FROM public.club_roles)"
            ))
    print("Import complete. Start the Flask app with DATABASE_URL set to this Supabase URL.")


if __name__ == "__main__":
    main()
