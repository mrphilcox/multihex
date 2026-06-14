# Invalid overlay fixtures

Deliberately-broken `layout-overlay` v1 files for validator diagnostic-path coverage.
Each file isolates a single defect. `manifest.json` is the machine-readable version.

- **structural** fixtures are detectable from the JSON alone.
- **file-aware** fixtures must be validated against the companion `sample16.bin`
  (16 bytes `00 01 .. 0f`, sha256 `be45cb2605bf36be…`).

Severities are suggestions — wire the `expected_code` values to whatever your
validator emits.

| Fixture | Layer | Severity | Suggested code | Defect |
|---|---|---|---|---|
| `invalid_duplicate_path.json` | structural | error | `duplicate_path` | two ranges share path 'header.magic' |
| `invalid_unknown_type.json` | structural | error | `unrecognized_type` | type 'u24be' is not in the recognized set |
| `invalid_unknown_status.json` | structural | error | `invalid_status` | status 'valid' is outside the closed vocabulary |
| `invalid_odd_length_hex.json` | structural | error | `malformed_hex` | raw_hex_preview 'abc' has odd length |
| `invalid_uppercase_hex.json` | structural | error | `malformed_hex` | raw_hex_preview 'DEADBE' is not lowercase |
| `invalid_negative_offset.json` | structural | error | `negative_offset` | offset is -1 |
| `invalid_negative_length.json` | structural | error | `negative_length` | length is -4 |
| `invalid_missing_length.json` | structural | error | `missing_required_field` | range has no 'length' |
| `invalid_bad_schema_version.json` | structural | error | `unsupported_schema` | schema.version is 2 (validator handles v1) |
| `invalid_overlap.json` | structural | warning | `overlapping_ranges` | field.a [0,6) overlaps field.b [4,10) |
| `invalid_out_of_bounds.json` | file-aware | error | `out_of_bounds` | offset 12 + length 8 > file size 16 |
| `invalid_size_mismatch.json` | file-aware | warning | `source_size_mismatch` | declared source_size 999 != actual 16 |
| `invalid_sha_mismatch.json` | file-aware | warning | `source_sha256_mismatch` | declared sha256 does not match file |
| `invalid_preview_mismatch.json` | file-aware | warning | `preview_mismatch` | raw_hex_preview ffffffff != actual 00010203 |
| `invalid_expected_mismatch.json` | file-aware | error | `expected_mismatch` | status=ok but expected_hex deadbeef != actual 00010203 |

## Suggested test shape

```python
import json, glob, os
MAN = json.load(open('fixtures_invalid/manifest.json'))
BY_FILE = {x['file']: x for x in MAN['fixtures']}

def test_every_fixture_is_rejected():
    for path in glob.glob('fixtures_invalid/invalid_*.json'):
        spec = BY_FILE[os.path.basename(path)]
        diags = validate(path, source='fixtures_invalid/sample16.bin')
        codes = {d.code for d in diags}
        assert spec['expected_code'] in codes, (path, codes)
        if spec['severity'] == 'error':
            assert any(d.code == spec['expected_code'] and d.is_error for d in diags)
```
