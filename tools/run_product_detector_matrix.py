"""Repeat installed-product detector runs with controls. Keep every verdict."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists. Do not overwrite reviewed results.')
    plan = [('stock-control', 'natural'), ('product', 'natural'), ('product', 'preloaded'),
            ('product', 'preloaded'), ('product', 'natural'), ('stock-control', 'natural')]
    rows = []
    for index, (mode, order) in enumerate(plan):
        process = subprocess.run([str(ROOT / '.venv/bin/python'), '-B',
            str(ROOT / 'tools/run_product_detectors.py'), '--mode', mode, '--order', order],
            cwd=ROOT, text=True, capture_output=True)
        if not process.stdout.strip():
            raise RuntimeError(process.stderr)
        row = json.loads(process.stdout.splitlines()[-1])
        row['index'] = index
        rows.append(row)
        args.output.write_text(json.dumps(rows, indent=2) + '\n')
        report_path = Path(row['run']) / 'report.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        print(Path(row['run']).name, mode, order, process.returncode, report.get('error'), flush=True)
        if process.returncode or row['observer']['status'] != 'PASS':
            raise SystemExit('Execution failed. Review retained results before further runs.')
    print('Completed all six planned runs. Detection is not an execution failure.')


if __name__ == '__main__':
    main()
