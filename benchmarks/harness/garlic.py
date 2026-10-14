"""Garlic v1.8 MCP adapter using a fresh server for each tool call.

The released server exited on a second tools/call in the same process. Each
measured query therefore includes a server launch, initialization and shutdown,
as well as the DuckDB CLI processes launched by the unmodified server.
"""
import csv
import io
import os
from pathlib import Path
import queue
import time

import psutil
from run import ANCHOR, CLASS, Process


def literal(value):
    return "'" + value.replace("'", "''") + "'"


TARGET = 'Liu3/a;->a(JZ)Ljava/lang/String;'
GIF = 'gifFilePath gifPath:'
BITMAP = 'Landroid/graphics/Bitmap;->getWidth()I'
OWNER = "split_part(method_raw, '->', 1)"
CALLERS = (
    "SELECT DISTINCT caller.method_raw AS value FROM java_cg_edges e "
    "JOIN java_cg_nodes caller ON caller.node_id=e.src_id "
    "JOIN java_cg_nodes callee ON callee.node_id=e.dst_id "
    f"WHERE callee.method_raw={literal(TARGET)}"
)
QUERIES = {
    'class': f"SELECT DISTINCT {OWNER} AS value FROM java_cg_nodes "
             f"WHERE starts_with(method_raw, {literal('L' + CLASS.replace('.', '/') + ';->')}) ORDER BY value",
    'method': f"SELECT DISTINCT {OWNER} AS value FROM java_cg_nodes "
              "WHERE lower(split_part(split_part(method_raw, '->', 2), '(', 1)) "
              "LIKE '%matchpayload%' ORDER BY value",
    'string': "SELECT DISTINCT split_part(n.method_raw, '->', 1) AS value "
              "FROM string_nodes s JOIN string_edges e ON e.string_id=s.id "
              "JOIN java_cg_nodes n ON n.node_id=e.method_id "
              f"WHERE s.str={literal(ANCHOR)} ORDER BY value",
    'callers': CALLERS + ' ORDER BY value',
    'twohop': f"WITH first_hop AS ({CALLERS}) "
              "SELECT DISTINCT caller.method_raw AS value FROM java_cg_edges e "
              "JOIN java_cg_nodes caller ON caller.node_id=e.src_id "
              "JOIN java_cg_nodes callee ON callee.node_id=e.dst_id "
              "JOIN first_hop f ON f.value=callee.method_raw ORDER BY value",
    'string_call': "SELECT DISTINCT n.method_raw AS value FROM string_nodes s "
                   "JOIN string_edges se ON se.string_id=s.id "
                   "JOIN java_cg_nodes n ON n.node_id=se.method_id "
                   "JOIN java_cg_edges ce ON ce.src_id=n.node_id "
                   "JOIN java_cg_nodes callee ON callee.node_id=ce.dst_id "
                   f"WHERE s.str={literal(GIF)} AND callee.method_raw={literal(BITMAP)} ORDER BY value",
}
UNSUPPORTED = {
    'four_fact': 'Imported schema has no field-access or numeric-constant references',
    'complex': 'Imported graph omits field accesses and call-site multiplicity',
}


class GarlicClient:
    def __init__(self, config, out, label, processes):
        self.config = config
        self.out = Path(out)
        self.label = label
        self.processes = processes
        self.counter = 0
        self.steps = {}
        self.db = self.out / (label + '-analysis.duckdb')
        self.env = dict(os.environ)
        self.env['PATH'] = str(Path(config['duckdb']).parent) + os.pathsep + self.env['PATH']

    def call(self, name, arguments, deadline):
        if time.perf_counter() >= deadline:
            raise queue.Empty()
        self.counter += 1
        process = Process([self.config['garlic'], '-m'],
                          self.out / f'{self.label}-garlic-{self.counter}.log', self.env)
        self.processes.append(process)
        try:
            response = process.request('initialize', {
                'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'dexsql-benchmark', 'version': '1'},
            }, max(.001, deadline-time.perf_counter()))
            if 'error' in response:
                raise RuntimeError(response)
            process.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            result = process.call(name, arguments, max(.001, deadline-time.perf_counter()))
            if not isinstance(result, str):
                raise RuntimeError(f'Unexpected {name} result: {result!r}')
            if result.lower().startswith(('err:', 'error:')) or result.startswith('cg_import FAILED'):
                raise RuntimeError(result)
            return result
        finally:
            try:
                for child in psutil.Process(process.p.pid).children(recursive=True):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
            except psutil.Error:
                pass
            process.close()
            self.processes.remove(process)

    def prepare(self):
        cg = self.out / (self.label + '-cg')
        for name, arguments in [
            ('call_graph', {'path': self.config['apk'], 'output_dir': str(cg)}),
            ('cg_import', {'cg_dir': str(cg), 'db_path': str(self.db)}),
        ]:
            start = time.perf_counter()
            self.call(name, arguments, start + 240)
            self.steps[name + '_ms'] = (time.perf_counter()-start)*1000
            print(self.label, name, round(self.steps[name + '_ms'], 2), flush=True)

    def query(self, kind, deadline):
        sql = f"SET threads={int(self.config.get('threads', 8))};\n" + QUERIES[kind]
        result = self.call('cg_query', {'db_path': str(self.db), 'sql': sql}, deadline)
        if result.strip() == '(no results)':
            return set()
        reader = csv.DictReader(io.StringIO(result))
        if reader.fieldnames != ['value']:
            raise RuntimeError(f'Unexpected query columns: {reader.fieldnames!r}')
        return {row['value'] for row in reader}
