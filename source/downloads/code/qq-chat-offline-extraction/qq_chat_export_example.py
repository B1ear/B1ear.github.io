"""Blog companion: export one contact from a frozen NTQQ database copy.

This file contains no account-specific configuration. The generated files contain
private chat data and are not publication assets. See the accompanying article.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

TABLES = ('c2c_msg_table', 'c2c_temp_msg_table')
FIELDS = {
    'msg_id': '40001', 'timestamp': '40050', 'direction': '40013',
    'sender_uid': '40020', 'sender_qq': '40033', 'peer_uid': '40021',
    'peer_qq': '40030', 'msg_type': '40011', 'blob': '40800',
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            value.update(block)
    return value.hexdigest()


def recover_wire(blob, parse_wire):
    """Interpret only known fields; retain the complete body as hexadecimal."""
    segments, texts = [], []
    for outer in parse_wire(blob):
        if outer.number != 40800 or outer.wire_type != 2:
            continue
        fields = parse_wire(outer.value)
        values = {field.number: field.value for field in fields}

        def utf8(number):
            value = values.get(number)
            if not isinstance(value, bytes):
                return None
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return None

        text = utf8(45101)
        if text:
            texts.append(text)
        width, height = values.get(45411, 0), values.get(45412, 0)
        if (values.get(45002) == 2 and isinstance(width, int)
                and isinstance(height, int) and width > 0 and height > 0):
            segment = {
                'type': 'image', 'filename': utf8(45402), 'width': width,
                'height': height, 'filesize': values.get(45405),
                'local_path': utf8(45812),
            }
            md5 = values.get(45406)
            if isinstance(md5, bytes):
                segment['md5_hex'] = md5.hex()
        elif text:
            segment = {'type': 'text', 'text': text}
        else:
            segment = {'type': 'unknown', 'content_type': values.get(45002)}
        segments.append(segment)
    return '\n'.join(texts) or None, {
        'type': 'partial_wire', 'segments': segments,
        'original_body_hex': blob.hex(),
    }


def export_chat(db, upstream, out, peer, key):
    import sqlcipher3.dbapi2 as sc
    sys.path.insert(0, str(upstream.resolve()))
    from msgdb.c2c.parser import parse_row
    from msgdb.proto.c2c_40800_parser import parse_40800
    from msgdb.proto.wire import parse_wire

    db, out = db.resolve(), out.resolve()
    wal = Path(str(db) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise RuntimeError('A nonempty WAL exists. Prepare a consistent snapshot first.')
    before = db.stat()
    source_hash = digest(db)
    with db.open('rb') as stream:
        header = stream.read(1024)
        if len(header) != 1024 or header[32:40] != b'QQ_NT DB':
            raise RuntimeError('Expected a QQ_NT DB snapshot; MSG0 backups are not supported.')
        if before.st_size <= 1024 or (before.st_size - 1024) % 4096:
            raise RuntimeError('Unexpected payload size for this parameter profile.')
        out.mkdir(parents=True, exist_ok=False)
        payload = out / 'source_payload.encrypted.db'
        with payload.open('xb') as target:
            shutil.copyfileobj(stream, target, 8 << 20)

    enc = raw = None
    report = {'completed': False, 'tables': {}, 'key_saved': False,
              'source_snapshot_sha256': source_hash}
    try:
        enc = sc.connect(payload.as_uri() + '?mode=ro&immutable=1', uri=True)
        enc.execute('PRAGMA cipher_log_level=NONE')
        enc.execute('PRAGMA cipher_page_size=4096')
        enc.execute("PRAGMA key='" + key.replace("'", "''") + "'")
        enc.execute('PRAGMA kdf_iter=4000')
        enc.execute('PRAGMA cipher_hmac_algorithm=HMAC_SHA1')
        enc.execute('PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_SHA512')
        enc.execute('SELECT count(*) FROM sqlite_master').fetchone()
        enc.row_factory = sc.Row
        mappings = enc.execute(
            'SELECT * FROM nt_uid_mapping_table WHERE [1002]=?', (peer,)
        ).fetchall()
        candidates = {str(peer)}
        for row in mappings:
            candidates.update(str(row[name]) for name in ('48902', '48912') if row[name])
        marks = ','.join('?' for _ in candidates)
        where = f'([40030]=? OR [40021] IN ({marks}))'
        params = [peer, *sorted(candidates)]
        raw_path = out / 'chat_raw.sqlite'
        raw = sqlite3.connect(raw_path)
        raw.execute('PRAGMA journal_mode=DELETE')
        raw.execute('PRAGMA synchronous=FULL')
        for table in TABLES:
            schema = enc.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()
            if schema is None:
                raise RuntimeError(f'Required table is missing: {table}')
            raw.execute(schema[0])
            matched = enc.execute(f'SELECT count(*) FROM {table} WHERE {where}', params).fetchone()[0]
            cursor = enc.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY [40001]', params)
            insert = f'INSERT INTO {table} VALUES ({",".join("?" for _ in cursor.description)})'
            copied = 0
            while rows := cursor.fetchmany(2000):
                raw.executemany(insert, [tuple(row) for row in rows])
                raw.commit()
                copied += len(rows)
            report['tables'][table] = {'matched': matched, 'copied': copied}
            if copied != matched:
                raise RuntimeError('Selected row count mismatch')
        schema = enc.execute("SELECT sql FROM sqlite_master WHERE name='nt_uid_mapping_table'").fetchone()[0]
        raw.execute(schema)
        for row in mappings:
            raw.execute('INSERT INTO nt_uid_mapping_table VALUES (' + ','.join('?' for _ in row) + ')', tuple(row))
        raw.commit()
        integrity = raw.execute('PRAGMA integrity_check').fetchall()
        report['output_integrity_check'] = integrity
        if integrity != [('ok',)]:
            raise RuntimeError('Output database integrity check failed')
        raw.row_factory = sqlite3.Row
        selection = ','.join(f'[{column}] AS {name}' for name, column in FIELDS.items())
        query = ' UNION ALL '.join(f"SELECT {selection}, '{table}' AS source_table FROM {table}" for table in TABLES)
        query += ' ORDER BY timestamp,msg_id'
        count = text_count = 0
        statuses, recovery = Counter(), Counter()
        previous = None
        tz = timezone(timedelta(hours=8))
        with (out / 'messages.jsonl').open('x', encoding='utf-8') as js, (out / 'chat.txt').open('x', encoding='utf-8-sig') as txt:
            txt.write('离线会话导出；时间为 UTC+08:00；附件仅保留元数据。\n\n')
            for row in raw.execute(query):
                state = parse_40800(row['blob']).status.value
                try:
                    item = parse_row(row).to_db_row()
                    if item['content']:
                        item['content'] = json.loads(item['content'])
                except Exception as exc:
                    item = {name: row[name] for name in FIELDS if name != 'blob'}
                    item.update(text=None, content=None, parse_error=type(exc).__name__)
                    state = 'parser_error'
                if state == 'wire_fallback':
                    try:
                        item['text'], item['content'] = recover_wire(row['blob'], parse_wire)
                        recovery['partial_wire'] += 1
                    except (ValueError, TypeError):
                        item['content'] = {'type': 'unknown', 'original_body_hex': row['blob'].hex()}
                        recovery['uninterpreted'] += 1
                item.update(parse_status=state, source_table=row['source_table'])
                if str(item.get('peer_qq') or 0) not in ('0', str(peer)):
                    raise RuntimeError('A selected row has a conflicting peer QQ number')
                order = (item['timestamp'] or 0, item['msg_id'])
                if previous is not None and order < previous:
                    raise RuntimeError('Message order check failed')
                previous = order
                try:
                    stamp = datetime.fromtimestamp(order[0], tz).isoformat(sep=' ')
                except (ValueError, OverflowError, OSError):
                    stamp = 'invalid_timestamp:' + str(order[0])
                item['time_utc_plus_8'] = stamp
                js.write(json.dumps(item, ensure_ascii=False) + '\n')
                content = item.get('content') or {}
                body = item.get('text') or '[' + str(content.get('type') or item.get('msg_type')) + ']'
                sender = item.get('sender_qq') or item.get('sender_uid') or 'unknown'
                txt.write(f'{stamp}  {sender}\n{body}\n\n')
                statuses[state] += 1
                count += 1
                text_count += bool(item.get('text'))
        expected = sum(item['matched'] for item in report['tables'].values())
        if count != expected:
            raise RuntimeError('JSON row count mismatch')
        raw.close()
        raw = None
        enc.close()
        enc = None
        after = db.stat()
        unchanged = ((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
                     and digest(db) == source_hash)
        if not unchanged:
            raise RuntimeError('Input snapshot changed while exporting')
        report.update(completed=True, message_count=count, text_message_count=text_count,
                      parse_status=dict(statuses), wire_recovery=dict(recovery),
                      source_snapshot_unchanged=unchanged, chronological_order_verified=True,
                      media_files_copied=False, source_integrity='not checked by this example')
        report['files'] = {name: {'sha256': digest(out / name), 'bytes': (out / name).stat().st_size}
                           for name in ('chat_raw.sqlite', 'messages.jsonl', 'chat.txt')}
    except Exception as exc:
        report['completed'] = False
        report['error'] = type(exc).__name__ + ': ' + str(exc).replace(key, '[REDACTED]')
        raise
    finally:
        if raw is not None:
            raw.close()
        if enc is not None:
            enc.close()
        (out / 'export_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, required=True, help='Frozen copy of nt_msg.db, including its 1024-byte header')
    ap.add_argument('--upstream', type=Path, required=True, help='Checkout of QQBackup/nt_msg_db_util')
    ap.add_argument('--out', type=Path, required=True, help='New private output directory; must not exist')
    args = ap.parse_args()
    peer = int(input('Target contact QQ number (local use only): ').strip())
    key = getpass.getpass('Database key (hidden input): ')
    if not key:
        raise SystemExit('An empty key is not supported')
    try:
        result = export_chat(args.db, args.upstream, args.out, peer, key)
    except Exception as exc:
        raise SystemExit(type(exc).__name__ + ': ' + str(exc).replace(key, '[REDACTED]'))
    print(json.dumps({'completed': result['completed'], 'message_count': result['message_count']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
