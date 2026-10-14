"""Reproduce the QQ lookup benchmark. Raw answers/logs remain in --out.

Requires compiled JadxProbe classes, a JADX all-in-one JAR, and, for jadx-mcp,
an isolated JADX config with the official plugin installed and a Python
environment containing the official MCP server's dependencies.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import threading
import time
import zipfile

ANCHOR = 'closeQuietly(): Exception when connHttp.getInputStream()!,There may be no network, or no INTERNET permission'
CLASS = 'com.tencent.mobileqq.activity.SplashActivity'
SQL = {
    'class': "SELECT descriptor FROM classes WHERE descriptor = 'Lcom/tencent/mobileqq/activity/SplashActivity;'",
    'method': "SELECT DISTINCT class_descriptor FROM class_methods WHERE method_name LIKE '%matchPayload%' ORDER BY class_descriptor",
    'string': "SELECT DISTINCT method_class FROM method_strings WHERE value = '" + ANCHOR + "' ORDER BY method_class",
}
NEEDLE = {'class': CLASS, 'method': 'matchPayload', 'string': ANCHOR}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def normalize(value):
    if value.startswith('L') and value.endswith(';'):
        value = value[1:-1].replace('/', '.')
    return value.replace('$', '.')


def rows_digest(rows):
    payload = json.dumps(sorted(set(rows)), ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


class Process:
    def __init__(self, args, log, env=None):
        self.log = open(log, 'w', encoding='utf-8')
        try:
            self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.log, text=True, encoding='utf-8', env=env,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except BaseException:
            self.log.close()
            raise
        self.q = queue.Queue()
        self.id = 0
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line.removeprefix('BENCH_JSON:')))
            except ValueError:
                pass
        self.q.put({'process_exit': self.p.poll()})

    def send(self, obj):
        self.p.stdin.write(json.dumps(obj) + '\n')
        self.p.stdin.flush()

    def request(self, method, params=None, timeout=180):
        self.id += 1
        request_id = self.id
        deadline = time.perf_counter() + timeout
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}})
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise queue.Empty
            result = self.q.get(timeout=remaining)
            if 'process_exit' in result:
                raise RuntimeError(result)
            if result.get('id') == request_id:
                return result

    def init(self):
        result = self.request('initialize', {
            'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'dexsql-benchmark', 'version': '1'},
        })
        if 'error' in result:
            raise RuntimeError(result)
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def call(self, name, arguments, timeout=180):
        response = self.request('tools/call', {'name': name, 'arguments': arguments}, timeout)
        result = response.get('result', response)
        if result.get('isError') or 'error' in response:
            raise RuntimeError(result)
        data = result.get('structuredContent')
        if data is None:
            contents = [c['text'] for c in result.get('content', []) if c.get('type') == 'text']
            try:
                data = json.loads('\n'.join(contents))
            except ValueError:
                data = '\n'.join(contents)
        return data

    def close(self):
        if self.p.poll() is None:
            self.p.terminate()
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self.log.close()


class Backend:
    def __init__(self, name, label, args):
        self.name = name
        self.processes = []
        self.args = args
        start = time.perf_counter()
        try:
            self.start(label)
        except BaseException:
            self.close()
            raise
        self.prepare_ms = (time.perf_counter() - start) * 1000

    def launch(self, command, log, env=None):
        p = Process(command, self.args.out / log, env)
        self.processes.append(p)
        return p

    def start(self, label):
        a = self.args
        env = dict(os.environ, JADX_CONFIG_DIR=str(a.jadx_config),
                   JADX_CACHE_DIR=str(a.out / (label + '-cache')))
        if self.name == 'dexsql':
            p = self.launch([str(a.dexsql), '--threads', str(a.threads), 'mcp',
                             '--timeout-ms', '120000', '--max-dex-bytes', '2147483648'], label + '.log')
            p.init()
            data = p.call('open_dataset', {'inputs': [str(a.apk)]}, 180)
            self.did = data['dataset_id']
            self.prepare_internal_ms = data.get('prepare_ms')
        else:
            p = self.launch([a.java, '-Xmx' + a.java_heap,
                             '-Djava.util.concurrent.ForkJoinPool.common.parallelism=' + str(a.threads),
                             '-cp', str(a.probe_classes) + os.pathsep + str(a.jadx_jar), 'JadxProbe',
                             'gui' if self.name == 'jadx-mcp' else 'core', str(a.apk), str(a.threads)],
                            label + '-java.log', env)
            data = p.q.get(timeout=240)
            if not data.get('ready'):
                raise RuntimeError(data)
            self.prepare_internal_ms = data.get('load_ms')
            if self.name == 'jadx-mcp':
                p = self.launch([str(a.mcp_python), str(a.jadx_mcp_server)], label + '-mcp.log')
                p.init()
        self.p = p

    def query(self, kind):
        start = time.perf_counter()
        timeout = self.args.timeout
        if self.name == 'dexsql':
            data = self.p.call('query', {'dataset_id': self.did, 'sql': [SQL[kind]],
                                        'limit': 1000, 'timing': True}, timeout)
            statement = data['statements'][0]
            if statement['truncated'] or statement['next_offset'] is not None:
                raise RuntimeError('incomplete result')
            rows = [normalize(row[0]['value']) for row in statement['rows']]
        elif self.name == 'jadx-core':
            self.p.send({'kind': kind, 'needle': NEEDLE[kind]})
            data = self.p.q.get(timeout=timeout)
            if 'error' in data or 'process_exit' in data:
                raise RuntimeError(data)
            rows = [normalize(value) for value in data['rows']]
        else:
            if kind == 'method':
                data = self.p.call('search_method_by_name', {'method_name': NEEDLE[kind]}, timeout)
                if isinstance(data, dict):
                    if 'error' in data:
                        raise RuntimeError(data)
                    if 'result' in data:
                        data = data['result']
                    elif 'results' in data:
                        data = data['results']
                if isinstance(data, str):
                    rows = data.strip().splitlines()
                elif isinstance(data, list):
                    rows = data
                else:
                    raise RuntimeError(data)
            else:
                data = self.p.call('search_classes_by_keyword', {
                    'search_term': 'SplashActivity' if kind == 'class' else ANCHOR,
                    'search_in': 'class' if kind == 'class' else 'code', 'count': 1000,
                }, timeout)
                if 'error' in data:
                    raise RuntimeError(data)
                if data.get('pagination', {}).get('has_more'):
                    raise RuntimeError('incomplete result')
                rows = data.get('items', [])
            rows = [normalize(value) for value in rows]
            if kind == 'class':
                rows = [value for value in rows if value == CLASS]
        rows = sorted(set(rows))
        ms = (time.perf_counter() - start) * 1000
        return {'wall_ms': ms, 'count': len(rows), 'answer_sha256': rows_digest(rows),
                'rows': rows, 'raw': data}

    def close(self):
        for process in reversed(self.processes):
            process.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apk', type=Path, required=True)
    ap.add_argument('--dexsql', type=Path)
    ap.add_argument('--jadx-jar', type=Path)
    ap.add_argument('--jadx-config', type=Path)
    ap.add_argument('--jadx-mcp-server', type=Path)
    ap.add_argument('--mcp-python', type=Path, default=Path(sys.executable))
    ap.add_argument('--probe-classes', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--java', default='java')
    ap.add_argument('--java-heap', default='24g')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--backends', default='dexsql,jadx-core,jadx-mcp')
    ap.add_argument('--trials', type=int, default=3)
    ap.add_argument('--cases', default='class,method,string')
    ap.add_argument('--warm', type=int, default=5)
    ap.add_argument('--timeout', type=int, default=60)
    a = ap.parse_args()
    names, cases = a.backends.split(','), a.cases.split(',')
    if set(names) - {'dexsql', 'jadx-core', 'jadx-mcp'} or set(cases) - SQL.keys():
        ap.error('unknown backend or case')
    if min(a.trials, a.warm, a.threads, a.timeout) < 1:
        ap.error('counts, threads, and timeout must be positive')
    required = ['apk']
    if 'dexsql' in names:
        required += ['dexsql']
    if set(names) & {'jadx-core', 'jadx-mcp'}:
        required += ['jadx_jar']
    if 'jadx-mcp' in names:
        required += ['jadx_config', 'jadx_mcp_server', 'mcp_python']
    for key in required:
        path = getattr(a, key)
        if path is None or not path.exists():
            ap.error('--' + key.replace('_', '-') + ' must point to an existing path')
    for key, value in vars(a).items():
        if isinstance(value, Path):
            setattr(a, key, value.resolve())
    if a.jadx_config is None:
        a.jadx_config = a.out / 'jadx-config'
    a.out.mkdir(parents=True, exist_ok=False)
    result = {'input': {'name': a.apk.name, 'bytes': a.apk.stat().st_size, 'sha256': digest(a.apk)},
              'dexsql_sha256': digest(a.dexsql) if a.dexsql else None,
              'jadx_sha256': digest(a.jadx_jar) if a.jadx_jar else None,
              'threads': a.threads, 'java_heap': a.java_heap, 'timeout_s': a.timeout,
              'warm_samples': a.warm, 'sql': SQL, 'runs': []}
    with zipfile.ZipFile(a.apk) as z:
        dex = [i for i in z.infolist() if i.filename.startswith('classes') and i.filename.endswith('.dex')]
        result['input'].update(dex_files=len(dex), dex_bytes=sum(i.file_size for i in dex))

    def save():
        (a.out / 'results.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    for trial in range(a.trials):
        ordered = names[trial % len(names):] + names[:trial % len(names)]
        for name in ordered:
            backend = None
            run = {'backend': name, 'trial': trial + 1, 'cases': {}}
            result['runs'].append(run)
            save()
            try:
                print('START', name, trial + 1, flush=True)
                backend = Backend(name, f'{name}-{trial + 1}', a)
                run.update(prepare_ms=backend.prepare_ms, prepare_internal_ms=backend.prepare_internal_ms)
                save()
                print('READY', name, round(backend.prepare_ms, 2), flush=True)
                for kind in cases:
                    record = {'status': 'running'}
                    run['cases'][kind] = record
                    save()
                    start = time.perf_counter()
                    try:
                        first = backend.query(kind)
                        record.update(status='ok', first_ms=first['wall_ms'], count=first['count'],
                                      answer_sha256=first['answer_sha256'], warm_ms=[])
                        (a.out / f'{name}-{trial + 1}-{kind}-first.json').write_text(
                            json.dumps(first, indent=2, ensure_ascii=False), encoding='utf-8')
                        backend.query(kind)  # One discarded warm-up.
                        for _ in range(a.warm):
                            sample = backend.query(kind)
                            if sample['answer_sha256'] != record['answer_sha256']:
                                raise RuntimeError('result changed across repetitions')
                            record['warm_ms'].append(sample['wall_ms'])
                        record['median_ms'] = statistics.median(record['warm_ms'])
                        print('CASE', name, kind, json.dumps(record), flush=True)
                    except queue.Empty:
                        record.update(status='timeout', elapsed_ms=(time.perf_counter() - start) * 1000)
                        print('TIMEOUT', name, kind, flush=True)
                        break
                    except Exception as error:
                        record.update(status='error', error=str(error)[:1500])
                        print('ERROR', name, kind, str(error)[:500], flush=True)
                        break
                    finally:
                        save()
            except Exception as error:
                run['error'] = str(error)[:1500]
                print('SETUP ERROR', name, str(error)[:500], flush=True)
                save()
            finally:
                if backend:
                    backend.close()
    print('SAVED', a.out / 'results.json', flush=True)


if __name__ == '__main__':
    main()
