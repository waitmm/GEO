"""Create a private invitation config; secrets go to files, never logs or Git."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--project-id', type=int, action='append', default=[])
    parser.add_argument('--admin', action='store_true')
    args = parser.parse_args()
    if not args.admin and not args.project_id:
        parser.error('Non-admin invitations require explicit project IDs')
    if any(i < 1 for i in args.project_id) or not args.name.strip():
        parser.error('Name and project IDs must be valid')
    if args.config.exists() or args.key_file.exists():
        parser.error('Destination exists; refusing to replace access credentials')
    key = secrets.token_urlsafe(32)
    config = {'accounts': [{'name': args.name.strip(), 'key_sha256': sha256(key.encode()).hexdigest(),
                            'admin': args.admin, 'project_ids': args.project_id}]}
    for path, data in [(args.key_file, key + '\n'), (args.config, json.dumps(config, indent=2) + '\n')]:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(data)
    print('Invitation created. Configure GEO_RELEASE_ACCESS_CONFIG with the config path; securely deliver the key file.')


if __name__ == '__main__':
    main()
