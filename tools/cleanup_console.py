#!/usr/bin/env python3
"""Preview Spotify cleanup, then ask whether to uninstall and erase its local data."""
import argparse
import ftplib
import getpass
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = 'PPSA05688'
CORE = 'NPXS40201'
STATE_FILES = ('original.record', 'patched.record', 'record-path', 'watcher.log',
               'watcher.lock', 'request', 'result', 'state.json', 'cache-salt')
LEGACY_FILES = ('017-ui1-token-incoming', '017-token-incoming')


class CleanupError(RuntimeError):
    pass


def api(base, endpoint, addr, *, body=None, **query):
    # Explicit console address on every call; never use the engine's default target.
    params = dict(query, addr=addr)
    url = base.rstrip('/') + '/api/ps5/' + endpoint
    data = None
    if body is None:
        url += '?' + urllib.parse.urlencode(params)
    else:
        data = json.dumps(dict(body, addr=addr)).encode()
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=75) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise CleanupError(
            f'PS5Upload engine returned HTTP {exc.code} for {endpoint}. '
            'Check the engine URL, supported management API and console helper connection.'
        ) from exc
    except urllib.error.URLError as exc:
        raise CleanupError(
            f'Cannot reach PS5Upload engine at {base}: {exc.reason}. '
            'Start your configured PS5Upload engine or pass --engine-url URL. '
            '--host selects the console; it does not start the computer-side engine. '
            'FTP and an ELF loader alone do not provide the uninstall API. '
            'Use --dry-run for an FTP-only preview.'
        ) from exc
    except (ValueError, UnicodeError) as exc:
        raise CleanupError('PS5Upload engine returned invalid JSON; check --engine-url') from exc
    if not isinstance(result, dict) or result.get('error'):
        raise CleanupError('Console management API returned an error')
    return result


def require_closed(result):
    if result.get('truncated') is not False or not isinstance(result.get('processes'), list):
        raise CleanupError('Cannot verify complete process list; cleanup refused')
    for process in result['processes']:
        name = str(process.get('name', '')).lower()
        if process.get('title_id') in (TITLE, CORE) or 'musiccore' in name or 'spotless' in name:
            raise CleanupError('Fully close Spotify and stop active Spotless payloads first')


def listing(ftp, path):
    # This console FTP server supports LIST, but not NLST/MLSD.
    lines = []
    ftp.retrlines('LIST ' + path, lines.append)
    entries = {}
    for line in lines:
        fields = line.split(None, 8)
        if len(fields) != 9 or fields[0][0] not in '-dl':
            raise CleanupError('Unrecognized FTP listing; cleanup refused')
        name = fields[8]
        if name in ('.', '..'):
            continue
        if '/' in name or '\r' in name or '\n' in name:
            raise CleanupError('Unsafe FTP entry')
        entries[name] = fields[0][0]
    return entries


def kind(ftp, path):
    parent, name = path.rsplit('/', 1)
    return listing(ftp, parent or '/').get(name)


def allowed(path):
    roots = [f'/user/{area}/{TITLE}' for area in ('app', 'appmeta', 'download', 'data')]
    roots += [f'/user/data/{CORE}', f'/user/download/{CORE}']
    if path in roots or any(path.startswith(root + '/') for root in roots):
        return True
    if re.fullmatch(r'/user/home/[0-9a-fA-F]+/savedata_prospero/' + TITLE + r'(?:/[^\r\n]+)?', path):
        return '..' not in path.split('/')
    return path in ['/data/spotless/' + name for name in STATE_FILES] + [
        '/data/spotify-auth-test/' + name for name in LEGACY_FILES]


def remove_tree(ftp, path, entry_kind, *, depth=0):
    if not allowed(path) or depth > 24 or entry_kind not in ('-', 'd'):
        raise CleanupError('Unsafe or unsupported removal target: ' + path)
    if entry_kind == 'd':
        for name, child_kind in listing(ftp, path).items():
            remove_tree(ftp, path + '/' + name, child_kind, depth=depth + 1)
        ftp.voidcmd('RMD ' + path)
    else:
        # Server returns 226 for DELE; FTP.delete() incorrectly rejects that success.
        ftp.voidcmd('DELE ' + path)
    if kind(ftp, path) is not None:
        raise CleanupError('Removal verification failed: ' + path)


def targets(ftp):
    result = []
    for parent, names in (
        ('/user', ('app', 'appmeta', 'download', 'data')),
    ):
        available = listing(ftp, parent)
        for area in names:
            if available.get(area) != 'd':
                continue
            entries = listing(ftp, parent + '/' + area)
            for title in ((TITLE, CORE) if area in ('download', 'data') else (TITLE,)):
                if title in entries:
                    result.append((parent + '/' + area + '/' + title, entries[title]))
    users = listing(ftp, '/user/home')
    for user, entry_kind in users.items():
        if entry_kind != 'd' or not re.fullmatch('[0-9a-fA-F]+', user):
            continue
        parent = '/user/home/' + user
        if listing(ftp, parent).get('savedata_prospero') == 'd':
            parent += '/savedata_prospero'
            entries = listing(ftp, parent)
            if TITLE in entries:
                result.append((parent + '/' + TITLE, entries[TITLE]))
    data = listing(ftp, '/data')
    for directory, names in (('spotless', STATE_FILES), ('spotify-auth-test', LEGACY_FILES)):
        if data.get(directory) != 'd':
            continue
        entries = listing(ftp, '/data/' + directory)
        for name in names:
            if name in entries:
                result.append(('/data/' + directory + '/' + name, entries[name]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Console IPv4/IPv6 address')
    parser.add_argument('--engine-url', default='http://127.0.0.1:19113', help='PS5Upload 6.6.1+ engine URL')
    parser.add_argument('--management-port', type=int, default=9111)
    parser.add_argument('--ftp-port', type=int, default=2121)
    parser.add_argument('--ftp-user', default='anonymous')
    parser.add_argument('--ask-ftp-password', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Show the preview and exit without prompting or making changes')
    args = parser.parse_args(argv)
    host = str(ipaddress.ip_address(args.host))
    addr = ('[' + host + ']' if ':' in host else host) + ':' + str(args.management_port)
    password = getpass.getpass('FTP password: ') if args.ask_ftp_password else os.environ.get('SPOTLESS_FTP_PASSWORD', '')
    with ftplib.FTP(timeout=30) as ftp:
        ftp.connect(host, args.ftp_port)
        ftp.login(args.ftp_user, password)
        plan = targets(ftp)
    print('Console:', host, '\nTitle:', TITLE)
    print('Sony app uninstall; then remove these title-scoped residual paths:')
    for path, _ in plan:
        print(' ', path)
    print('This erases Spotify login/session/cache and Spotless recovery files.')
    print('Downloaded PKGs, shared system components and other titles are preserved.')
    print('Uninstall requires a working PS5Upload engine/helper and fully closed Spotify/Spotless.')
    if args.dry_run:
        print('FTP-only preview; running processes and uninstall readiness were not checked.')
        print('Dry run complete. No changes made.')
        return
    try:
        answer = input(f'Continue with uninstall and data removal on {host} ({TITLE})? [y/N]: ')
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled. No changes made.')
        return
    if answer.strip().lower() not in ('y', 'yes'):
        print('Cancelled. No changes made.')
        return
    # Reconnect after confirmation; the user may have left the preview open long
    # enough for the original FTP session to expire. Verify both services first.
    with ftplib.FTP(timeout=30) as ftp:
        ftp.connect(host, args.ftp_port)
        ftp.login(args.ftp_user, password)
        require_closed(api(args.engine_url, 'process/list', addr))
        result = api(args.engine_url, 'app/unregister', addr, body={'title_id': TITLE})
        if (result.get('ok') is not True or result.get('sony_uninstall_refused') is not False
                or str(result.get('sony_uninstall_rc')).lower() != '0x00000000'):
            raise CleanupError('Sony uninstall did not confirm success; residual cleanup stopped')
        info = api(args.engine_url, 'appinfo', addr, title_id=TITLE)
        if info.get('ok') is not True or info.get('rows') != []:
            raise CleanupError('App registration still present or unverifiable; cleanup stopped')
        require_closed(api(args.engine_url, 'process/list', addr))
        # Re-enumerate after Sony uninstall. Never delete from a stale preview.
        for path, entry_kind in targets(ftp):
            remove_tree(ftp, path, entry_kind)
            print('Removed:', path)
        if targets(ftp):
            raise CleanupError('Residual files remain; cleanup incomplete')
        print('Complete. Spotify uninstalled; known title data and Spotless state removed.')


if __name__ == '__main__':
    try:
        main()
    except (CleanupError, OSError, ValueError, ftplib.Error, urllib.error.URLError) as exc:
        raise SystemExit('Cleanup stopped: ' + str(exc))
