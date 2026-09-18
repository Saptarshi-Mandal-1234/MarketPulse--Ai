"""Generate editable PBIP/PBIR and import-mode semantic model from published exports."""
import argparse
import hashlib
import json
from pathlib import Path

root = Path.cwd()
pointer = json.loads((root / 'data/dashboard/current.json').read_text())
manifest = json.loads((Path(pointer['path']) / 'manifest.json').read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', default='dashboards/MarketPulsePolished')
args = parser.parse_args()
folder = root / args.output
project_filename = ('MarketPulse AI - Enhanced.pbip' if folder.name == 'MarketPulsePolished'
                    else 'MarketPulseRelease.pbip')
report = folder / 'MarketPulse.Report'
model = folder / 'MarketPulse.SemanticModel'
base = 'https://developer.microsoft.com/json-schemas/fabric/item/'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


write(folder / project_filename, {'version': '1.0',
      'artifacts': [{'report': {'path': 'MarketPulse.Report'}}], 'settings': {'enableAutoRecovery': True}})
write(report / 'definition.pbir', {'$schema': base + 'report/definitionProperties/2.0.0/schema.json',
      'version': '4.0', 'datasetReference': {'byPath': {'path': '../MarketPulse.SemanticModel'}}})
write(model / 'definition.pbism', {'$schema': base + 'semanticModel/definitionProperties/1.0.0/schema.json',
      'version': '1.0', 'settings': {}})
tables = []
for name, fields in manifest['schema'].items():
    fields = dict(fields)
    if name == 'History':
        fields['session_date'] = 'dateTime'
    converted = ', '.join('{' + json.dumps(c) + ', ' +
                           {'double': 'type number', 'boolean': 'type logical',
                            'string': 'type text', 'dateTime': 'type date'}[t]
                           + '}' for c, t in fields.items())
    query = [
        'let',
        f'  Pointer = Json.Document(File.Contents("{(root / "data/dashboard/current.json").as_posix()}")),',
        (f'  Source = Csv.Document(File.Contents(Pointer[path] & "/{name}.csv"), '
         '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),'),
        '  Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
        '  Nulls = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, Table.ColumnNames(Headers)),',
        f'  Typed = Table.TransformColumnTypes(Nulls, {{{converted}}}, "en-US")',
        'in Typed']
    columns = [{'name': c, 'dataType': t, 'sourceColumn': c, 'summarizeBy': 'none',
                **({'formatString': 'yyyy-MM-dd'} if t == 'dateTime' else
                   {'formatString': '0.00%'} if c in ['value', 'return_1d', 'annualized_volatility',
                   'volatility_20', 'endpoint_return', 'endpoint_cagr', 'observed_max_drawdown'] else {'formatString': '0.0000'} if c in ['brier', 'mae', 'rmse', 'isolation_score'] else {})}
               for c, t in fields.items()]
    tables.append({'name': name, 'columns': columns, 'partitions': [
        {'name': name, 'mode': 'import', 'source': {'type': 'm', 'expression': query}}]})
relationships = [{'name': 'Symbols_' + t['name'], 'fromTable': t['name'], 'fromColumn': 'symbol',
                  'toTable': 'Symbols', 'toColumn': 'symbol', 'crossFilteringBehavior': 'oneDirection'}
                 for t in tables if t['name'] != 'Symbols' and 'symbol' in manifest['schema'][t['name']]]
write(model / 'model.bim', {'name': 'MarketPulse', 'compatibilityLevel': 1606,
      'model': {'culture': 'en-US', 'defaultPowerBIDataSourceVersion': 'powerBI_V3',
                'tables': tables, 'relationships': relationships,
                'dataAccessOptions': {'legacyRedirects': True, 'returnErrorValuesAsNull': True}}})
definition = report / 'definition'
write(definition / 'version.json', {'$schema': base + 'report/definition/versionMetadata/1.0.0/schema.json',
                                  'version': '2.0.0'})
write(definition / 'report.json', {'$schema': base + 'report/definition/report/2.0.0/schema.json',
                                 'themeCollection': {}})


LABELS = {
    'symbol': 'Instrument', 'session_date': 'As of', 'adj_close': 'Adjusted close (INR)',
    'return_1d': 'Daily return', 'signal': 'Technical reading', 'risk_band': 'Risk level',
    'data_status': 'Data availability', 'annualized_volatility': 'Annualized volatility',
    'observed_max_drawdown': 'Max drawdown', 'beta_vs_nifty': 'Beta vs NIFTY',
    'endpoint_cagr': 'CAGR', 'rsi_14': 'RSI (14)', 'roc_auc': 'ROC AUC',
    'balanced_accuracy': 'Balanced accuracy', 'brier': 'Brier score', 'mae': 'MAE',
    'rmse': 'RMSE', 'as_of_date': 'Input date', 'target_date': 'Forecast date',
    'value': 'Probability / return', 'isolation_anomaly': 'Unusual pattern',
    'statistical_anomaly': 'Unusual return', 'abnormal_volume': 'Unusual volume',
    'latest_input_missing': 'Older indicators', 'return_z': 'Return z-score',
    'relative_volume': 'Relative volume', 'insight': 'What this means',
}


def field(table, column, aggregate=False):
    value = {'Column': {'Expression': {'SourceRef': {'Entity': table}}, 'Property': column}}
    if aggregate:
        value = {'Aggregation': {'Expression': value, 'Function': 1}}
    return {'field': value, 'queryRef': f'{table}.{column}', 'displayName': LABELS.get(column, column.replace('_', ' ').title())}


def visual(page, name, kind, roles, x, y, width, height, title):
    name = hashlib.sha256((page + name).encode()).hexdigest()[:20]
    def literal(value):
        return {'expr': {'Literal': {'Value': value}}}
    objects = ({'grid': [{'properties': {'textSize': literal('13D')}}],
                'values': [{'properties': {'wordWrap': literal('true')}}],
                'columnHeaders': [{'properties': {'fontSize': literal('12D')}}]}
               if kind == 'tableEx' else
               {'categoryAxis': [{'properties': {'axisType': literal("'Scalar'"),
                                                 'fontSize': literal('12D')}}],
                'valueAxis': [{'properties': {'fontSize': literal('12D')}}]}
               if kind == 'lineChart' else {})
    write(definition / 'pages' / page / 'visuals' / name / 'visual.json', {
        '$schema': base + 'report/definition/visualContainer/2.4.0/schema.json', 'name': name,
        'position': {'x': x, 'y': y + 80, 'z': y + x, 'height': height, 'width': width, 'tabOrder': y + x},
        'visual': {'visualType': kind, 'objects': objects, 'query': {'queryState': {
            role: {'projections': [field(*f) for f in fields]} for role, fields in roles.items()}},
            'visualContainerObjects': {
                'background': [{'properties': {'show': literal('true'),
                    'color': {'solid': {'color': literal("'#F4F8FB'")}},
                    'transparency': literal('0D')}}],
                'title': [{'properties': {
                'show': {'expr': {'Literal': {'Value': 'true'}}},
                'text': {'expr': {'Literal': {'Value': "'" + title + "'"}}},
                'fontSize': literal('20D'),
                'fontColor': {'solid': {'color': literal("'#16324F'")}}}}]},
            'drillFilterOtherVisuals': True}})


pages = [('overview', 'Market Overview'), ('explorer', 'Stock Explorer'),
         ('technical', 'Technical Analysis'), ('prediction', 'Prediction Center'),
         ('risk', 'Risk Analytics'), ('anomalies', 'Anomalies'), ('insights', 'Daily Insights')]
write(definition / 'pages/pages.json', {'$schema': base + 'report/definition/pagesMetadata/1.0.0/schema.json',
                                      'pageOrder': [p for p, _ in pages], 'activePageName': 'overview'})
for page, title in pages:
    write(definition / 'pages' / page / 'page.json', {
        '$schema': base + 'report/definition/page/2.0.0/schema.json', 'name': page,
        'displayName': title, 'displayOption': 'FitToPage', 'width': 1280, 'height': 880})
    if page not in ['insights', 'prediction']:
        visual(page, 'instrument', 'slicer', {'Values': [('Symbols', 'symbol')]},
               20, 20, 230, 740, 'Instrument')


def table(page, name, entity, columns, x=270, y=20, w=990, h=740, title=None):
    visual(page, name, 'tableEx', {'Values': [(entity, c) for c in columns]},
           x, y, w, h, title or name)


def line(page, name, columns, y):
    roles = {'Category': [('History', 'session_date')], 'Y': [('History', c, True) for c in columns]}
    if len(columns) == 1:
        roles['Series'] = [('Symbols', 'symbol')]
    else:
        name += ' — average of selected instruments'
    visual(page, name, 'lineChart', roles,
           270, y, 990, 350, name)


table('overview', 'Market snapshot', 'Market', ['symbol', 'session_date', 'adj_close',
      'return_1d', 'signal', 'risk_band', 'data_status'], h=410)
table('overview', 'Read before interpreting', 'Insights', ['topic', 'insight'], y=450, h=310)
line('explorer', 'Adjusted price history', ['adj_close'], 20)
line('explorer', 'Observed volume', ['volume'], 410)
line('technical', 'Moving averages', ['ema_12', 'ema_26'], 20)
line('technical', 'MACD and signal', ['macd', 'macd_signal'], 410)
table('prediction', 'Model evaluation — historical research', 'Models', ['target', 'model', 'split',
      'selection', 'balanced_accuracy', 'roc_auc', 'brier', 'mae', 'rmse'], x=20, w=1240, h=370)
table('prediction', 'Forecast eligibility — skipped values remain blank', 'Forecasts',
      ['symbol', 'as_of_date', 'target_date', 'target', 'value', 'status'], x=20, y=420, w=1240, h=340)
table('risk', 'Historical risk and performance', 'Performance', ['symbol', 'annualized_volatility',
      'observed_max_drawdown', 'beta_vs_nifty', 'sharpe', 'sortino', 'endpoint_cagr'], h=400)
table('risk', 'Latest available risk — check the date', 'Market', ['symbol', 'session_date', 'risk_band',
      'annualized_volatility', 'rsi_14', 'data_status'], y=440, h=320)
table('anomalies', 'Anomaly watch — flags require review', 'Anomalies', ['symbol',
      'session_date', 'isolation_anomaly', 'statistical_anomaly', 'abnormal_volume'], h=350)
table('anomalies', 'Supporting evidence — latest available observations', 'Anomalies', ['symbol',
      'session_date', 'isolation_score', 'return_z', 'relative_volume', 'latest_input_missing'], y=410, h=350)

table('insights', 'Daily observations and evidence', 'Insights', ['topic', 'insight'], x=20, w=1240)
print(folder / project_filename)

# A consistent, editable masthead anchors every report page.
for page, title in pages:
    name = hashlib.sha256((page + 'masthead').encode()).hexdigest()[:20]
    write(definition / 'pages' / page / 'visuals' / name / 'visual.json', {
        '$schema': base + 'report/definition/visualContainer/2.4.0/schema.json',
        'name': name,
        'position': {'x': 20, 'y': 12, 'z': 0, 'width': 1240, 'height': 66, 'tabOrder': 0},
        'visual': {'visualType': 'textbox', 'objects': {'general': [{'properties': {
            'paragraphs': [{'textRuns': [
                {'value': 'MARKETPULSE AI   /   ' + title,
                 'textStyle': {'fontFamily': 'Segoe UI', 'fontSize': '22pt',
                               'fontWeight': 'bold', 'color': '#16324F'}},
                {'value': '   |   Indian equity research',
                 'textStyle': {'fontFamily': 'Segoe UI', 'fontSize': '12pt', 'color': '#527286'}}]}]
        }}]}, 'drillFilterOtherVisuals': True}})
