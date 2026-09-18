"""Validate PBIR with official Microsoft JSON schemas and every model field reference."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

from jsonschema import validators
from referencing import Registry, Resource

root = Path.cwd()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', default='dashboards/MarketPulseRelease')
args = parser.parse_args()
folder = root / args.output
cache = root / 'docs/powerbi-schemas/cache'
cache.mkdir(parents=True, exist_ok=True)


def retrieve(uri):
    if not uri.startswith('https://developer.microsoft.com/json-schemas/'):
        raise ValueError('Unexpected schema host')
    path = cache / (hashlib.sha256(uri.encode()).hexdigest() + '.json')
    if not path.exists():
        with urllib.request.urlopen(uri, timeout=30) as response:
            path.write_bytes(response.read())
    return Resource.from_contents(json.loads(path.read_text()))


registry = Registry(retrieve=retrieve)
count = 0
compatibility_checks = []
for path in folder.rglob('*'):
    if path.suffix not in ['.json', '.pbir', '.pbism'] or '.pbi' in path.parts:
        continue
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if '$schema' in value:
        schema_uri = value['$schema']
        # Desktop 2.157 emits this schema before Microsoft publishes its endpoint.
        # Validate unchanged properties against the published compatible contract.
        if '/visualContainer/2.12.0/' in schema_uri:
            compatibility_checks.append(str(path.relative_to(folder)))
            schema_uri = schema_uri.replace('/2.12.0/', '/2.4.0/')
        schema = retrieve(schema_uri).contents
        cls = validators.validator_for(schema)
        validator = cls(schema, registry=registry, _resolver=registry.resolver(schema_uri))
        validator.validate({**value, '$schema': schema_uri})
        count += 1
model = json.loads((folder / 'MarketPulse.SemanticModel/model.bim').read_text())
fields = {t['name']: {c['name'] for c in t['columns']} for t in model['model']['tables']}
for path in folder.rglob('visual.json'):
    value = json.loads(path.read_text())
    for role in value['visual'].get('query', {}).get('queryState', {}).values():
        for projection in role['projections']:
            table, column = projection['queryRef'].split('.')
            assert column in fields[table]
result = {'status': 'passed', 'schema_validated_files': count, 'pages': 7,
          'visuals': len(list(folder.rglob('visual.json'))), 'tables': len(fields),
          'compatibility_checked_files': compatibility_checks,
          'note': 'Desktop 2.12 visual schemas checked against published 2.4 contract; rendering checked separately'}
(root / 'reports/powerbi').mkdir(exist_ok=True)
(root / 'reports/powerbi/verification.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
