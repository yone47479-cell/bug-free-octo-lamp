"""北京时间、按日期切分验证样本，以及可回滚的多文件导出。"""
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

__version__ = "1.1"

BJT = timezone(timedelta(hours=8))


def beijing_now():
    return datetime.now(BJT).replace(tzinfo=None)


def date_split(rows, key, ratios=(0.6, 0.8)):
    """同一天的样本始终在同一段，避免同场多玩法跨段。"""
    dates = sorted({str(key(r))[:10] for r in rows})
    if len(dates) < 5:
        return [], [], []
    a = dates[max(1, int(len(dates) * ratios[0]))]
    b = dates[min(len(dates)-1, max(2, int(len(dates) * ratios[1])))]
    return ([r for r in rows if str(key(r))[:10] < a],
            [r for r in rows if a <= str(key(r))[:10] < b],
            [r for r in rows if str(key(r))[:10] >= b])


@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if os.name == 'nt':
            import msvcrt
            f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path, text):
    """同目录独立临时文件，写完再替换；失败保留原文件并清理临时文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=str(path.parent), prefix='.' + path.name + '.',
                                         suffix='.tmp', delete=False) as f:
            temp = Path(f.name)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _json(path, value):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def _recover(journal):
    if not journal.exists():
        return
    state = json.loads(journal.read_text(encoding='utf-8'))
    stage = Path(state['stage'])
    if state['state'] != 'committed':
        errors = []
        for item in reversed(state['files']):
            target = Path(item['target'])
            backup = stage / item['backup']
            try:
                if item['existed']:
                    if target.exists() and target.read_bytes() == backup.read_bytes():
                        continue
                    temp = target.with_name(target.name + '.recover.tmp')
                    shutil.copy2(backup, temp)
                    os.replace(temp, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise OSError("部分文件暂时无法恢复，关闭占用文件后重试：" + "；".join(errors))
    journal.unlink()
    shutil.rmtree(stage, ignore_errors=True)


def atomic_batch(files, manifest):
    """所有内容先落临时文件；异常回滚，进程中断后下次写入前恢复。

    多个路径不能由文件系统同时替换，manifest 最后提交标明完整批次。
    """
    manifest = Path(manifest).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    journal = manifest.with_name(manifest.name + '.journal')
    with _lock(manifest.with_name(manifest.name + '.lock')):
        _recover(journal)
        stage = Path(tempfile.mkdtemp(prefix='.batch-', dir=manifest.parent))
        batch_id = uuid.uuid4().hex
        payload = {Path(p).resolve(): text for p, text in files.items()}
        payload[manifest] = json.dumps({'batch_id': batch_id, 'time_bjt': beijing_now().isoformat(),
                                       'files': [str(p) for p in payload]}, ensure_ascii=False, indent=2)
        entries = []
        try:
            for i, (target, text) in enumerate(payload.items()):
                target.parent.mkdir(parents=True, exist_ok=True)
                device = target.stat().st_dev if target.exists() else target.parent.stat().st_dev
                if device != stage.stat().st_dev:
                    raise OSError('批量导出的文件必须位于同一磁盘')
                backup, new = str(i) + '.bak', str(i) + '.new'
                existed = target.exists()
                if existed:
                    shutil.copy2(target, stage / backup)
                with (stage / new).open('w', encoding='utf-8', newline='') as f:
                    f.write(text); f.flush(); os.fsync(f.fileno())
                entries.append({'target': str(target), 'backup': backup, 'new': new, 'existed': existed})
            state = {'state': 'prepared', 'stage': str(stage), 'files': entries}
            _json(journal, state)
            for item in entries:
                os.replace(stage / item['new'], item['target'])
            state['state'] = 'committed'
            _json(journal, state)
        except BaseException:
            if journal.exists():
                _recover(journal)
            else:
                shutil.rmtree(stage, ignore_errors=True)
            raise
        _recover(journal)
        return batch_id
