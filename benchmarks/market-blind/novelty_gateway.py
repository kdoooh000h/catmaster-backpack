#!/usr/bin/env python3
"""Plugin-only benchmark gateway; production routing and user prompts stay intact.

The caller freezes installed-before.json outside the repository and supplies its
SHA-256. Only candidate names matching that snapshot appear in protocol evidence.
No installation roots or private catalogs are inspected by this launcher.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata


def private_bytes(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('benchmark_unsafe_snapshot_path')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 2*1024*1024:
        raise ValueError('benchmark_snapshot_not_private')
    return path.read_bytes()


def name_keys(name):
    if not isinstance(name,str) or not name.strip():
        raise ValueError('benchmark_invalid_skill_name')
    normalized = unicodedata.normalize('NFKC',name).strip().casefold()
    return {normalized,normalized.rsplit(':',1)[-1]}


class Inventory:
    def __init__(self, path, expected_digest, connection):
        self.path = Path(path)
        self.connection = Path(connection)
        self.run = self.path.parent
        if (self.path.name != 'installed-before.json' or not re.fullmatch('[a-f0-9]{64}',expected_digest)
                or not self.connection.is_relative_to(self.run) or self.connection.parent == self.run):
            raise ValueError('benchmark_inventory_binding_mismatch')
        for directory in (self.run,self.connection.parent):
            info = directory.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('benchmark_run_not_private')
        self.digest = expected_digest
        raw = private_bytes(self.path)
        if hashlib.sha256(raw).hexdigest() != self.digest:
            raise ValueError('benchmark_inventory_digest_mismatch')
        value = json.loads(raw)
        if not isinstance(value,dict) or not isinstance(value.get('names'),list):
            raise ValueError('benchmark_invalid_inventory')
        self.names = set()
        for name in value['names']:
            self.names.update(name_keys(name))
        descriptor = private_bytes(self.connection)
        self.connection_digest = hashlib.sha256(descriptor).hexdigest()
        self.binding = json.loads(descriptor)
        if (self.binding.get('version') != 2 or self.binding.get('enabled') is not True
                or self.binding.get('data_root') != str(self.connection.parent)):
            raise ValueError('benchmark_inventory_binding_mismatch')

    def check(self, connection):
        if (Path(connection.get('_descriptor','')) != self.connection
                or {k:v for k,v in connection.items() if k != '_descriptor'} != self.binding):
            raise ValueError('benchmark_inventory_binding_mismatch')
        if hashlib.sha256(private_bytes(self.path)).hexdigest() != self.digest:
            raise ValueError('benchmark_inventory_digest_mismatch')
        if hashlib.sha256(private_bytes(self.connection)).hexdigest() != self.connection_digest:
            raise ValueError('benchmark_connection_changed')

    def existing(self, name):
        return bool(name_keys(name) & self.names)


def novel_market(base, inventory):
    class NovelMarket(base):
        def __init__(self, gateway, connection):
            inventory.check(connection)
            self.excluded_existing = []
            super().__init__(gateway,connection)

        def check_novel(self, rows):
            inventory.check(self.connection)
            if any(inventory.existing(row['name']) for row in rows):
                raise ValueError('benchmark_existing_skill_excluded')

        def prepare(self, arguments):
            inventory.check(self.connection)
            if arguments.get('kind') != 'plugin':
                raise ValueError('benchmark_plugin_only')
            self.excluded_existing = []
            result = super().prepare(arguments)
            return {**result,'excluded_existing':list(self.excluded_existing)}

        def portable_guidance_fit(self, plan):
            inventory.check(self.connection)
            eligible = []
            excluded = plan.setdefault('excluded_existing',[])
            for row in plan['skills']:
                if inventory.existing(row['name']):
                    if row['name'] not in excluded:
                        excluded.append(row['name'])
                    if row['name'] not in self.excluded_existing:
                        self.excluded_existing.append(row['name'])
                else:
                    eligible.append(row)
            plan['skills'] = eligible
            return bool(eligible) and super().portable_guidance_fit(plan)

        def view(self, plan):
            return {**super().view(plan),'excluded_existing':list(plan.get('excluded_existing',[]))}

        def connect_skills(self, plan):
            self.check_novel(plan['skills'])
            return super().connect_skills(plan)

        def bound_skill_keys(self, token):
            inventory.check(self.connection)
            keys = super().bound_skill_keys(token)
            state = self.gateway.public_access.registry(self.data)
            self.check_novel([state['items'][key] for key in keys])
            return keys

        def bound_skill_context(self, token):
            inventory.check(self.connection)
            context = super().bound_skill_context(token)
            state = self.gateway.public_access.registry(self.data)
            self.check_novel([state['items'][key] for key in context['keys']])
            return context

    return NovelMarket


def install(protocol, market_module, inventory):
    """Wrap only this process's benchmark imports; retain original implementations."""
    market_type = novel_market(market_module.Market,inventory)
    market_module.Market = protocol.Market = market_type
    original_dispatch, original_catalog = protocol.dispatch, protocol.tool_catalog

    def dispatch(gateway, connection, reader, market, name, arguments):
        inventory.check(connection)
        if name == 'acquire_skill':
            if not isinstance(arguments,dict) or not isinstance(arguments.get('market_selection'),str):
                raise ValueError('benchmark_market_selection_required')
        result = original_dispatch(gateway,connection,reader,market,name,arguments)
        inventory.check(connection)
        if name == 'acquire_skill' and result.get('status') == 'selected':
            # Inspect only the selected public name before protocol serialization.
            if inventory.existing(result.get('name')):
                raise ValueError('benchmark_existing_skill_excluded')
        return result

    def tool_catalog(gateway):
        rows = original_catalog(gateway)
        for row in rows:
            if row['name'] == 'acquire_skill':
                schema = row['inputSchema']
                row['inputSchema'] = {**schema,'required':list(dict.fromkeys([*schema.get('required',[]),'market_selection']))}
        return rows

    protocol.dispatch, protocol.tool_catalog = dispatch, tool_catalog
    return market_type


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter-root',required=True)
    parser.add_argument('--runtime-root',required=True)
    parser.add_argument('--connection',required=True)
    parser.add_argument('--inventory',required=True)
    parser.add_argument('--inventory-sha256',required=True)
    args = parser.parse_args()
    inventory = Inventory(args.inventory,args.inventory_sha256,args.connection)
    sys.path.insert(0,str(Path(args.adapter_root).resolve(strict=True)))
    import market_gateway
    import market_connect
    import market_protocol
    gateway = market_gateway.load_gateway(args.runtime_root)
    connection = {**gateway.load_connection(args.connection),'_descriptor':args.connection}
    install(market_protocol,market_connect,inventory)
    return market_protocol.serve(gateway,connection)


if __name__ == '__main__':
    raise SystemExit(main())
