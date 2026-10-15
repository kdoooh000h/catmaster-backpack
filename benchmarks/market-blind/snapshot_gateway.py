#!/usr/bin/env python3
"""A/B launcher: freeze complete public metadata, never packages or business calls.

Both arms share an owner-only corpus. An unseen query may be read once from its
normal public source and then frozen for both arms. Original observation times
remain; this explicitly tests a fixed corpus, not live marketplace freshness.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from novelty_gateway import Inventory, install, private_bytes


def save(path, value):
    content = json.dumps(value, ensure_ascii=False).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)


def freeze(corpus, key, read):
    path = corpus / (hashlib.sha256(key.encode()).hexdigest() + '.json')
    lock = os.open(path.with_suffix('.lock'), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            value = json.loads(private_bytes(path))
            if value.get('key') != key:
                raise ValueError('benchmark_corpus_key_mismatch')
            return copy.deepcopy(value['snapshot'])
        result = read()  # A failure never becomes a cached successful partial list.
        save(path, {'key': key, 'observed_at': time.time(), 'snapshot': result})
        return copy.deepcopy(result)
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser()
    for name in ('adapter-root', 'runtime-root', 'connection', 'inventory', 'inventory-sha256', 'corpus'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--family', choices=['skill', 'plugin', 'mcp'], required=True)
    parser.add_argument('--browser-review-dir', help='Private host browser review queue for an HTML-only run')
    args = parser.parse_args()
    inventory = Inventory(args.inventory, args.inventory_sha256, args.connection)
    corpus = Path(args.corpus)
    corpus.mkdir(mode=0o700, parents=True, exist_ok=True)
    if corpus.is_symlink() or corpus.stat().st_mode & 0o077:
        raise ValueError('benchmark_corpus_not_private')
    sys.path.insert(0, str(Path(args.adapter_root).resolve(strict=True)))
    import market_gateway
    import market_connect
    import market_protocol
    import market_registry
    gateway = market_gateway.load_gateway(args.runtime_root)
    connection = {**gateway.load_connection(args.connection), '_descriptor': args.connection}
    market_type = install(market_protocol, market_connect, inventory, args.family)
    original_catalog = market_type.plugin_catalog

    def catalog(self, source):
        snapshot = freeze(corpus, 'plugin:' + source, lambda: original_catalog(self, source))
        snapshot['catalog'] = {'mode': 'benchmark_frozen_complete_catalog', 'coverage': 'complete_at_snapshot',
                               'checked_at': snapshot.get('checked_at'), 'limitation': 'Frozen A/B public corpus; new entries may be absent.'}
        return snapshot

    market_type.plugin_catalog = catalog
    original_pages = market_registry.pages
    market_registry.pages = lambda query, deadline: freeze(
        corpus, 'registry-query:' + query, lambda: original_pages(query, deadline))
    base = gateway.Router

    class NovelRouter(base):
        def _choose(self, need, candidates, purpose='skill'):
            inventory.check(connection)
            if purpose == 'skill' and candidates and not all(row.name.startswith('group-') for row in candidates):
                candidates = [row for row in candidates if not inventory.existing(row.description.split(':', 1)[0])]
                if not candidates:
                    return {'status': 'none', 'confidence': 1, 'skill': None, 'reason': 'benchmark_existing_candidates_excluded'}
            return super()._choose(need, candidates, purpose)

    gateway.Router = NovelRouter
    if args.browser_review_dir:
        import browser_review
        browser_review.install(market_protocol,connection,args.browser_review_dir)
    return market_protocol.serve(gateway, connection)


if __name__ == '__main__':
    raise SystemExit(main())
