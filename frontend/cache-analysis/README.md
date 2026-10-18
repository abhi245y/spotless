# Cache format reference

`cache_record.py` independently decodes, validates and rebuilds WebKit format-16
records for native implementation checks. It is a development tool, not a deployment
method; do not upload its output over live app cache files.

`spotifytv-record.header` holds independently generated metadata and synthetic
response headers for the pinned bundle. `tests/run_checks.py` appends your local
`frontend/spotifytv.js` to it to build the `spotifytv-record.original` test fixture.
`test-salt.bin` contains the public eight-byte test value `unitSalt`. Neither file
is a console capture or a real cache salt.
