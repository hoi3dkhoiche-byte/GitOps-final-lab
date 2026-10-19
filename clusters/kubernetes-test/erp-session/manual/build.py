#!/usr/bin/env python3
"""Build/test a versioned runtime JAR in the temporary Java 8 Pod."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

TARGET = 'de/metas/ui/web/session/SessionConfig.class'
RESOURCE = 'de/metas/ui/web/session/jdbc/schema-postgresql.sql'
ARTIFACTS = [
    ('spring-session-jdbc-2.4.2.jar',
     'org/springframework/session/spring-session-jdbc/2.4.2',
     'ede69c9c5a0639b2b9241166fad03a5c98e3ee58a0b6a7bab02d6934f1feeb52'),
    ('spring-jdbc-5.3.4.jar', 'org/springframework/spring-jdbc/5.3.4',
     '9721b4df45d6281196d0601115b18b076c240efb8000f35d236cf266aa6a1368'),
]
JUNIT = ('junit-platform-console-standalone-1.7.1.jar',
         'org/junit/platform/junit-platform-console-standalone/1.7.1',
         'e588d4dab5c8898b241c2a25938bf0b933ab77518626f14028cce403df7ce33d')


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fetch(directory, artifact):
    name, relative, expected = artifact
    dst = directory / name
    url = 'https://repo.maven.apache.org/maven2/' + relative + '/' + name
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as response, dst.open('wb') as out:
                shutil.copyfileobj(response, out)
            if digest(dst) != expected:
                raise RuntimeError('Artifact SHA256 mismatch: ' + name)
            return dst
        except Exception:
            if attempt == 2:
                raise


def assert_unsigned(archive):
    if any(n.upper().startswith('META-INF/') and
           n.upper().endswith(('.SF', '.RSA', '.DSA', '.EC')) for n in archive.namelist()):
        raise RuntimeError('Signed archive: refusing to replace class files')


def rewrite(source, destination, replacements):
    """Preserve every original entry except explicit replacements; store nested JARs."""
    remaining = dict(replacements)
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(destination, 'w', allowZip64=True) as new:
        assert_unsigned(old)
        if len(old.namelist()) != len(set(old.namelist())):
            raise RuntimeError('Duplicate ZIP entries in source archive')
        for info in old.infolist():
            payload = remaining.pop(info.filename, None)
            if payload is None:
                payload = old.read(info)
            updated = copy.copy(info)
            if info.filename.startswith('BOOT-INF/lib/') and info.filename.endswith('.jar'):
                updated.compress_type = zipfile.ZIP_STORED
            new.writestr(updated, payload)
        for name, payload in remaining.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED if name.startswith('BOOT-INF/lib/') else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            new.writestr(info, payload)


def main():
    work, patch, out = Path('/work'), Path(__file__).resolve().parent, Path('/out')
    original = work / 'base.jar'
    jars, classes, changed, tests = (work / n for n in ('lib', 'original-classes', 'patch-classes', 'test-classes'))
    for directory in (jars, classes, changed, tests):
        directory.mkdir(parents=True, exist_ok=True)
    owner = []
    with zipfile.ZipFile(original) as fat:
        assert_unsigned(fat)
        required = {'spring-boot-2.4.3.jar', 'spring-session-core-2.4.2.jar',
                    'spring-core-5.3.4.jar', 'spring-tx-5.3.4.jar', 'postgresql-42.3.3.jar'}
        lib_names = {Path(n).name for n in fat.namelist() if n.startswith('BOOT-INF/lib/')}
        if not required <= lib_names:
            raise RuntimeError('Original image dependency versions do not match the checked API')
        for info in fat.infolist():
            if info.filename.startswith('BOOT-INF/classes/') and not info.is_dir():
                relative = Path(info.filename).relative_to('BOOT-INF/classes')
                if '..' in relative.parts:
                    raise RuntimeError('Unsafe class path')
                target = classes / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(fat.read(info))
            if info.filename.startswith('BOOT-INF/lib/') and info.filename.endswith('.jar'):
                payload = fat.read(info)
                (jars / Path(info.filename).name).write_bytes(payload)
                with zipfile.ZipFile(io.BytesIO(payload)) as nested:
                    if TARGET in nested.namelist():
                        owner.append(info.filename)
        if 'BOOT-INF/classes/' + TARGET in fat.namelist():
            owner.append('BOOT-INF/classes')
    if len(owner) != 1:
        raise RuntimeError('Expected exactly one original SessionConfig class, found ' + repr(owner))

    for artifact in ARTIFACTS:
        fetch(jars, artifact)
    classpath = str(changed) + os.pathsep + str(classes) + os.pathsep + str(jars / '*')
    subprocess.run(['javac', '-J-Xmx768m', '-proc:none', '-encoding', 'UTF-8',
                    '-source', '1.8', '-target', '1.8', '-cp', classpath, '-d', str(changed),
                    str(patch / 'SessionConfig.java'), str(patch / 'JdbcSessionStore.java')], check=True)
    resource = changed / RESOURCE
    resource.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(patch / 'schema-postgresql.sql', resource)

    # Tests use an independent, disposable PostgreSQL Pod, never the ERP database.
    junit = fetch(work, JUNIT)
    subprocess.run(['javac', '-proc:none', '-encoding', 'UTF-8', '-source', '1.8', '-target', '1.8',
                    '-cp', classpath + os.pathsep + str(junit), '-d', str(tests),
                    str(patch / 'JdbcSessionStoreTest.java')], check=True)
    expanded = [str(changed), str(classes), str(tests)] + [str(p) for p in sorted(jars.glob('*.jar'))]
    # Put JDBC drivers on the JVM classpath, including when DriverManager was
    # initialized before JUnit installed its test context class loader.
    subprocess.run(['java', '-Xmx768m', '-Djdbc.drivers=org.postgresql.Driver',
                    '-cp', os.pathsep.join([str(junit)] + expanded),
                    'org.junit.platform.console.ConsoleLauncher', '--disable-ansi-colors', '--select-class',
                    'de.metas.ui.web.session.jdbc.JdbcSessionStoreTest', '--fail-if-no-tests',
                    '--config', 'junit.jupiter.execution.parallel.enabled=false',
                    '--reports-dir', '/out/test-results'], check=True)

    additions = {p.relative_to(changed).as_posix(): p.read_bytes()
                 for p in changed.rglob('*') if p.is_file()}
    replacements = {}
    if owner[0] == 'BOOT-INF/classes':
        replacements.update({'BOOT-INF/classes/' + k: v for k, v in additions.items()})
    else:
        patched_module = work / 'patched-module.jar'
        rewrite(jars / Path(owner[0]).name, patched_module, additions)
        replacements[owner[0]] = patched_module.read_bytes()
    for name, _, _ in ARTIFACTS:
        replacements['BOOT-INF/lib/' + name] = (jars / name).read_bytes()
    with zipfile.ZipFile(original) as fat:
        if 'BOOT-INF/classpath.idx' in fat.namelist():
            index = fat.read('BOOT-INF/classpath.idx').decode('utf-8')
            for name, _, _ in ARTIFACTS:
                if 'BOOT-INF/lib/' + name not in index:
                    index = index.rstrip() + '\n- "BOOT-INF/lib/' + name + '"\n'
            replacements['BOOT-INF/classpath.idx'] = index.encode()
    replacements['META-INF/session-jdbc-manual.json'] = json.dumps({
        'baseImage': os.environ['BASE_IMAGE'],
        'springSessionJdbc': '2.4.2', 'springJdbc': '5.3.4',
        'sources': {n: digest(patch / n) for n in ('SessionConfig.java', 'JdbcSessionStore.java', 'schema-postgresql.sql')}
    }, sort_keys=True).encode()
    temp = out / 'api-session-building.jar'
    rewrite(original, temp, replacements)
    with zipfile.ZipFile(temp) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Output archive CRC check failed')
        for info in archive.infolist():
            if info.filename.startswith('BOOT-INF/lib/') and info.filename.endswith('.jar'):
                if info.compress_type != zipfile.ZIP_STORED:
                    raise RuntimeError('Nested JAR must be uncompressed: ' + info.filename)
    sha = digest(temp)
    filename = 'metasfresh-api-session-' + sha + '.jar'
    temp.replace(out / filename)
    result = {'file': filename, 'sha256': sha, 'baseImage': os.environ['BASE_IMAGE'],
              'sessionTests': 'passed', 'testDatabase': 'session_jdbc_test'}
    (out / 'result.json').write_text(json.dumps(result, indent=2))
    print('ARTIFACT_SHA256=' + sha, flush=True)
    print('FACTORY_POSTGRES_TESTS=PASSED', flush=True)


if __name__ == '__main__':
    main()
