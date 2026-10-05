"""Bahja PMU backend on Modal (free $30/mo credit, no card).

Deploys the Flask app in C:/turf/bahja-pmu/backend as a Modal web endpoint.
Writable state (SQLite DBs) lives on the persistent 'bahja-data' volume;
read-only code + dna archive ship inside the image.
"""
import modal

app = modal.App("bahja-backend")

VOL = modal.Volume.from_name("bahja-data", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "Flask==3.1.1",
        "flask-cors==5.0.1",
        "gunicorn==23.0.0",
        "requests==2.32.3",
        "numpy==2.5.1",
        "beautifulsoup4==4.15.0",
        "psycopg2-binary==2.9.10",
    )
    .add_local_dir(
        r"C:\turf\bahja-pmu\backend",
        remote_path="/app/backend",
        ignore=["__pycache__", "*.db-shm", "*.db-wal", "*.db-journal",
                "logs", ".vercel", "archive.db", "archive_slim*.db",
                "dna_archive.db", "users.db", "archives", "cache"],
    )
)


@app.function(
    image=image,
    volumes={"/data": VOL},
    env={
        "ARCHIVE_DB": "/data/archive_slim.db",
        "ARCHIVE_DIR": "/data/archives",
        "DNA_ARCHIVE_DB": "/data/dna_archive.db",
        "USERS_DB": "/data/users.db",
        "FLIP_DB": "/data/flip_log.db",
    },
    timeout=300,
)
@modal.wsgi_app()
def flask_app():
    import os
    import sys

    sys.path.insert(0, "/app/backend")
    os.chdir("/app/backend")
    os.makedirs("/data/archives", exist_ok=True)
    from app import app as flask_app

    return flask_app
