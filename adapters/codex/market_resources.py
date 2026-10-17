"""Read Jev-selected resources of a pinned, granted market plugin package."""

from pathlib import Path


def plugin_resource(router, module, arguments):
    # Return None to leave non-plugin packages and manifest-based bundles with
    # the existing runtime. No fabricated external-source registration.
    if (not isinstance(arguments, dict) or set(arguments) - {'need', 'selection', 'project_root'}
            or any(not isinstance(v, str) for v in arguments.values()) or 'selection' not in arguments):
        raise ValueError('invalid_arguments')
    need = arguments.get('need', '').strip()
    if not 1 <= len(need) <= 2000:
        raise ValueError('invalid_need')
    project = arguments.get('project_root') if 'project_root' in arguments else router._claims(arguments['selection'])[2]
    router._project(project)
    if router.access.scope is not None and router.access.scope != project:
        raise ValueError('project_scope_mismatch')
    if module.runtime._sensitive(need):
        return {'status': 'sensitive_need_rejected', 'execution': 'not_performed'}
    key, item, root = router._verify(arguments['selection'], project)
    if item.get('provenance', {}).get('kind') != 'plugin' or module.resources.manifest(root):
        return None
    if module.runtime._maintenance_request(need):
        return {'status': 'maintenance_required', 'execution': 'not_performed'}
    paths = [p for p in sorted(root.rglob('*')) if p.is_file()
             and p.relative_to(root).parts[0] not in {'SKILL.md', '.backpack-source.json', 'upstream-notices'}]
    if len(paths) > 192:
        return {'status': 'unsupported', 'reason': 'plugin_resource_catalog_too_large', 'execution': 'not_performed'}
    candidates = [module.runtime.Skill(p.relative_to(root).as_posix(),
                  'Resource in this plugin: ' + p.relative_to(root).as_posix(), p) for p in paths]
    decision = router._choose(need, candidates, purpose='resource') if candidates else {'status': 'none', 'confidence': 1.0}
    if decision['status'] != 'selected':
        return {**decision, 'execution': 'not_performed'}
    selected = decision.get('skill')
    if selected not in {c.name for c in candidates}:
        raise ValueError('invalid_resource_choice')
    bundle = [module.external_skills.read(root, selected)]
    workspace = router._workspace(key, item, root, project, bundle, None)
    for row in bundle:
        row['absolute_path'] = str(Path(workspace['root']) / row['path'])
    if router._item(key, project)[0] != item:
        raise ValueError('public_access_changed')
    module.external_skills.record(router.data, module.runtime, key, item['name'], 'external', 'resource_acquired')
    return {'status': 'selected', 'resources': bundle,
            'routing': {k: v for k, v in decision.items() if k != 'skill'},
            'execution': 'not_performed', 'workspace': workspace, 'package_root': workspace['root'],
            'instruction': workspace['instruction'] + ' Report authorized Skill use through report_skill_use with one stable run id; acquisition is not execution.'}
