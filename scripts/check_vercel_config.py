"""Validate vercel.json against Vercel's current official schema (read-only network)."""
import json
from pathlib import Path
import subprocess
import jsonschema


def main():
    root=Path(__file__).resolve().parents[1]
    response=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','20','https://openapi.vercel.sh/vercel.json'],check=True,capture_output=True,text=True)
    schema=json.loads(response.stdout)
    # The published schema declares draft-04 but contains modern schema constructs.
    # Draft7 validates those constructs, including const, rather than failing its old meta-schema.
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.Draft7Validator(schema).validate(json.loads((root/'vercel.json').read_text()))
    print('vercel.json validates against https://openapi.vercel.sh/vercel.json')

if __name__=='__main__':main()
