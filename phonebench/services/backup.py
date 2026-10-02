import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime

from flask import current_app
from sqlalchemy import inspect

from ..extensions import db


def create_database_backup():
    engine = db.engine
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Online database backup is currently supported for SQLite installations only.")
    source = engine.raw_connection()
    os.makedirs(current_app.config["BACKUP_FOLDER"], exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"phonebench-{stamp}.sqlite"
    suffix = 1
    while os.path.exists(os.path.join(current_app.config["BACKUP_FOLDER"], filename)):
        filename = f"phonebench-{stamp}-{suffix:02d}.sqlite"
        suffix += 1
    destination = os.path.join(current_app.config["BACKUP_FOLDER"], filename)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    uploads = current_app.config["UPLOAD_FOLDER"]
    archive = shutil.make_archive(destination[:-7], "zip", root_dir=uploads) if os.path.isdir(uploads) else None
    return {"database": filename, "attachments": os.path.basename(archive) if archive else None}


def export_records():
    result = {}
    inspector = inspect(db.engine)
    for table in inspector.get_table_names():
        rows = db.session.execute(db.text(f'SELECT * FROM "{table}"')).mappings().all()
        result[table] = [{key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in row.items()} for row in rows]
    return json.dumps(result, ensure_ascii=False, indent=2)


def restore_database(file_storage):
    if db.engine.dialect.name != "sqlite":
        raise RuntimeError("Restore is supported only for SQLite installations.")
    filename = file_storage.filename or ""
    if not filename.lower().endswith((".sqlite", ".db")):
        raise ValueError("Select a SQLite database backup (.sqlite or .db).")
    database_path = db.engine.url.database
    if not database_path or not os.path.isabs(database_path):
        raise RuntimeError("The configured SQLite database path must be absolute for restore.")
    os.makedirs(os.path.dirname(database_path), exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=os.path.dirname(database_path), suffix=".sqlite", delete=False) as temp_file:
        temporary_path = temp_file.name
    try:
        file_storage.save(temporary_path)
        check = sqlite3.connect(temporary_path)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("The selected database failed SQLite integrity validation.")
        finally:
            check.close()
        db.session.remove()
        db.engine.dispose()
        if os.path.exists(database_path):
            backup_path = database_path + f".pre-restore-{datetime.utcnow():%Y%m%d-%H%M%S}"
            shutil.copy2(database_path, backup_path)
        os.replace(temporary_path, database_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def restore_attachments(file_storage):
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    parent = os.path.dirname(upload_folder)
    os.makedirs(parent, exist_ok=True)
    temporary_folder = tempfile.mkdtemp(prefix="phonebench-uploads-", dir=parent)
    try:
        try:
            archive = zipfile.ZipFile(file_storage.stream)
        except zipfile.BadZipFile as exc:
            raise ValueError("The selected attachment backup is not a valid ZIP archive.") from exc
        total_size = 0
        with archive:
            for info in archive.infolist():
                if info.is_dir() or "/" in info.filename or "\\" in info.filename or os.path.basename(info.filename) != info.filename:
                    raise ValueError("The archive contains an unexpected path.")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("Symbolic links are not allowed in attachment backups.")
                if not re.fullmatch(r"[a-f0-9]{40}\.[a-z0-9]{1,10}", info.filename):
                    raise ValueError("The archive contains an unexpected attachment name.")
                extension = info.filename.rsplit(".", 1)[1]
                if extension not in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]:
                    raise ValueError("The archive contains a disallowed file type.")
                total_size += info.file_size
                if total_size > 1024 * 1024 * 1024:
                    raise ValueError("The attachment archive exceeds the 1 GiB restore limit.")
                destination = os.path.join(temporary_folder, info.filename)
                with archive.open(info) as source, open(destination, "wb") as target:
                    shutil.copyfileobj(source, target)
        old_folder = None
        if os.path.exists(upload_folder):
            old_folder = upload_folder + f".pre-restore-{datetime.utcnow():%Y%m%d-%H%M%S}"
            os.replace(upload_folder, old_folder)
        try:
            os.replace(temporary_folder, upload_folder)
        except OSError:
            if old_folder and not os.path.exists(upload_folder):
                os.replace(old_folder, upload_folder)
            raise
    finally:
        if os.path.isdir(temporary_folder):
            shutil.rmtree(temporary_folder)
