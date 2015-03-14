#!/usr/bin/env python3
'''
Created on 26/09/2013
@author: Carlo Pires <carlopires@gmail.com>
'''
import os
import sys
import warnings
import argparse
import urllib.request
import shutil
import hashlib
import pwd
import re
import subprocess
from subprocess import call

# This should really be included in apt-cache policy output... it is already
# in the Release file...
RELEASE_CODENAME_LOOKUP = {
    '1.1': 'buzz',
    '1.2': 'rex',
    '1.3': 'bo',
    '2.0': 'hamm',
    '2.1': 'slink',
    '2.2': 'potato',
    '3.0': 'woody',
    '3.1': 'sarge',
    '4.0': 'etch',
    '5.0': 'lenny',
    '6.0': 'squeeze',
    '7.0': 'wheezy',
    '8.0': 'jessie',
    }

TESTING_CODENAME = 'unknown.new.testing'

RELEASES_ORDER = list(RELEASE_CODENAME_LOOKUP.items())
RELEASES_ORDER.sort()
RELEASES_ORDER = list(list(zip(*RELEASES_ORDER))[1])
RELEASES_ORDER.extend(['stable', 'testing', 'unstable', 'sid'])


def lookup_codename(release, unknown=None):
    m = re.match(r'(\d+)\.(\d+)(r(\d+))?', release)
    if not m:
        return unknown

    shortrelease = '%s.%s' % m.group(1, 2)
    return RELEASE_CODENAME_LOOKUP.get(shortrelease, unknown)

# LSB compliance packages... may grow eventually
PACKAGES = 'lsb-core lsb-cxx lsb-graphics lsb-desktop ' \
    'lsb-languages lsb-multimedia lsb-printing lsb-security'

modnamere = re.compile(r'lsb-(?P<module>[a-z0-9]+)-(?P<arch>[^ ]+)'
                       r'(?: \(= (?P<version>[0-9.]+)\))?')


def valid_lsb_versions(version, module):
    # If a module is ever released that only appears in >= version, deal
    # with that here
    if version == '3.0':
        return ['2.0', '3.0']
    elif version == '3.1':
        if module in ('desktop', 'qt4'):
            return ['3.1']
        elif module == 'cxx':
            return ['3.0', '3.1']
        else:
            return ['2.0', '3.0', '3.1']
    elif version == '3.2':
        if module == 'desktop':
            return ['3.1', '3.2']
        elif module == 'qt4':
            return ['3.1']
        elif module in ('printing', 'languages', 'multimedia'):
            return ['3.2']
        elif module == 'cxx':
            return ['3.0', '3.1', '3.2']
        else:
            return ['2.0', '3.0', '3.1', '3.2']
    elif version == '4.0':
        if module == 'desktop':
            return ['3.1', '3.2', '4.0']
        elif module == 'qt4':
            return ['3.1']
        elif module in ('printing', 'languages', 'multimedia'):
            return ['3.2', '4.0']
        elif module == 'security':
            return ['4.0']
        elif module == 'cxx':
            return ['3.0', '3.1', '3.2', '4.0']
        else:
            return ['2.0', '3.0', '3.1', '3.2', '4.0']
    elif version == '4.1':
        if module == 'desktop':
            return ['3.1', '3.2', '4.0', '4.1']
        elif module == 'qt4':
            return ['3.1']
        elif module in ('printing', 'languages', 'multimedia'):
            return ['3.2', '4.0', '4.1']
        elif module == 'security':
            return ['4.0', '4.1']
        elif module == 'cxx':
            return ['3.0', '3.1', '3.2', '4.0', '4.1']
        else:
            return ['2.0', '3.0', '3.1', '3.2', '4.0', '4.1']

    return [version]


# This is Debian-specific at present
def check_modules_installed():
    # Find which LSB modules are installed on this system
    C_env = os.environ.copy()
    C_env['LC_ALL'] = 'C'

    output = subprocess.Popen(['dpkg-query', '-f',
                               "${Version} ${Provides}\n", '-W'] +
                              PACKAGES.split(),
                              env=C_env,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              close_fds=True).communicate()[0].decode('utf-8')

    if not output:
        return []

    modules = set()
    for line in output.split(os.linesep):
        if not line:
            break

        version, provides = line.split(' ', 1)
        # Debian package versions can be 3.2-$REV, 3.2+$REV or 3.2~$REV.
        version = re.split('[-+~]', version, 1)[0]
        for pkg in provides.split(','):
            mob = modnamere.search(pkg)
            if not mob:
                continue

            mgroups = mob.groupdict()
            # If no versioned provides...
            if mgroups.get('version'):
                module = '%(module)s-%(version)s-%(arch)s' % mgroups
                modules.add(module)
            else:
                module = mgroups['module']
                for v in valid_lsb_versions(version, module):
                    mgroups['version'] = v
                    module = '%(module)s-%(version)s-%(arch)s' % mgroups
                    modules.add(module)

    modules = list(modules)
    modules.sort()
    return modules

longnames = {'v': 'version', 'o': 'origin', 'a': 'suite',
             'c': 'component', 'l': 'label'}


def parse_policy_line(data):
    retval = {}
    bits = data.split(',')
    for bit in bits:
        kv = bit.split('=', 1)
        if len(kv) > 1:
            k, v = kv[:2]
            if k in longnames:
                retval[longnames[k]] = v
    return retval


def release_index(x):
    suite = x[1].get('suite')
    if suite:
        if suite in RELEASES_ORDER:
            return int(len(RELEASES_ORDER) - RELEASES_ORDER.index(suite))
        else:
            return suite
    return 0


def compare_release(x, y):
    warnings.warn('compare_release(x,y) is deprecated; '
                  'please use the release_index(x) as key for sort() instead.',
                  DeprecationWarning, stacklevel=2)

    suite_x_i = release_index(x)
    suite_y_i = release_index(y)

    try:
        return suite_x_i - suite_y_i
    except TypeError:
        return (suite_x_i > suite_y_i) - (suite_x_i < suite_y_i)


def parse_apt_policy():
    data = []

    C_env = os.environ.copy()
    C_env['LC_ALL'] = 'C'

    policy = subprocess.Popen(['apt-cache', 'policy'],
                              env=C_env,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              close_fds=True).communicate()[0].decode('utf-8')

    for line in policy.split('\n'):
        line = line.strip()
        m = re.match(r'(-?\d+)', line)
        if m:
            priority = int(m.group(1))
        if line.startswith('release'):
            bits = line.split(' ', 1)
            if len(bits) > 1:
                data.append((priority, parse_policy_line(bits[1])))

    return data


FTP_DEBIAN = 'ftp.debian-ports.org'


def guess_release_from_apt(origin='Debian', component='main',
                           ignoresuites=('experimental'),
                           label='Debian',
                           alternate_olabels={'Debian Ports': FTP_DEBIAN}):
    releases = parse_apt_policy()

    if not releases:
        return None

    # We only care about the specified origin, component, and label
    releases = [x for x in releases if (
        x[1].get('origin', '') == origin and
        x[1].get('component', '') == component and
        x[1].get('label', '') == label) or (
        x[1].get('origin', '') in alternate_olabels and
        x[1].get('label', '') ==
            alternate_olabels.get(x[1].get('origin', '')))]

    # Check again to make sure we didn't wipe out all of the releases
    if not releases:
        return None

    releases.sort(key=lambda tpl: tpl[0], reverse=True)

    # We've sorted the list by descending priority, so the first entry should
    # be the "main" release in use on the system

    max_priority = releases[0][0]
    releases = [x for x in releases if x[0] == max_priority]
    releases.sort(key=release_index)

    return releases[0][1]


def guess_debian_release():
    distinfo = {}

    distinfo['ID'] = 'Debian'
    # Use /etc/dpkg/origins/default to fetch the distribution name
    etc_dpkg_origins_default = os.environ.get('LSB_ETC_DPKG_ORIGINS_DEFAULT',
                                              '/etc/dpkg/origins/default')

    if os.path.exists(etc_dpkg_origins_default):
        try:
            with open(etc_dpkg_origins_default) as dpkg_origins_file:
                for line in dpkg_origins_file:
                    try:
                        (header, content) = line.split(': ', 1)
                        header = header.lower()
                        content = content.strip()
                        if header == 'vendor':
                            distinfo['ID'] = content
                    except ValueError:
                        pass
        except IOError as msg:
            print('Unable to open ' + etc_dpkg_origins_default + ':', str(msg),
                  file=sys.stderr)

    kern = os.uname()[0]
    if kern in ('Linux', 'Hurd', 'NetBSD'):
        distinfo['OS'] = 'GNU/'+kern
    elif kern == 'FreeBSD':
        distinfo['OS'] = 'GNU/k'+kern
    elif kern in ('GNU/Linux', 'GNU/kFreeBSD'):
        distinfo['OS'] = kern
    else:
        distinfo['OS'] = 'GNU'

    distinfo['DESCRIPTION'] = '%(ID)s %(OS)s' % distinfo

    etc_debian_version = os.environ.get('LSB_ETC_DEBIAN_VERSION',
                                        '/etc/debian_version')
    if os.path.exists(etc_debian_version):
        try:
            with open(etc_debian_version) as debian_version:
                release = debian_version.read().strip()
        except IOError as msg:
            print('Unable to open ' + etc_debian_version + ':', str(msg),
                  file=sys.stderr)
            release = 'unknown'

        if not release[0:1].isalpha():
            # /etc/debian_version should be numeric
            codename = lookup_codename(release, 'n/a')
            distinfo.update({'RELEASE': release, 'CODENAME': codename})
        elif release.endswith('/sid'):
            if release.rstrip('/sid').lower().isalpha() != 'testing':
                global TESTING_CODENAME
                TESTING_CODENAME = release.rstrip('/sid')
            distinfo['RELEASE'] = 'testing/unstable'
        else:
            distinfo['RELEASE'] = release

    # Only use apt information if we did not get the proper information
    # from /etc/debian_version or if we don't have a codename
    # (which will happen if /etc/debian_version does not contain a
    # number but some text like 'testing/unstable' or 'lenny/sid')
    #
    # This is slightly faster and less error prone in case the user
    # has an entry in his /etc/apt/sources.list but has not actually
    # upgraded the system.
    if not distinfo.get('CODENAME'):
        rinfo = guess_release_from_apt()
        if rinfo:
            release = rinfo.get('version')

        # Special case Debian-Ports as their Release file has 'version': '1.0'
        if release == '1.0' and rinfo.get('origin') == 'Debian Ports' and \
                rinfo.get('label') == 'ftp.debian-ports.org':
            release = None
            rinfo.update({'suite': 'unstable'})

        if release:
            codename = lookup_codename(release, 'n/a')
        else:
            release = rinfo.get('suite', 'unstable')
            if release == 'testing':
                # Would be nice if I didn't have to hardcode this.
                codename = TESTING_CODENAME
            else:
                codename = 'sid'
        distinfo.update({'RELEASE': release, 'CODENAME': codename})

    if distinfo.get('RELEASE'):
        distinfo['DESCRIPTION'] += ' %(RELEASE)s' % distinfo
    if distinfo.get('CODENAME'):
        distinfo['DESCRIPTION'] += ' (%(CODENAME)s)' % distinfo

    return distinfo


# Whatever is guessed above can be overridden in /etc/lsb-release
def get_lsb_information():
    distinfo = {}
    etc_lsb_release = os.environ.get('LSB_ETC_LSB_RELEASE', '/etc/lsb-release')
    if os.path.exists(etc_lsb_release):
        try:
            with open(etc_lsb_release) as lsb_release_file:
                for line in lsb_release_file:
                    line = line.strip()
                    if not line:
                        continue
                    # Skip invalid lines
                    if '=' not in line:
                        continue
                    var, arg = line.split('=', 1)
                    if var.startswith('DISTRIB_'):
                        var = var[8:]
                        if arg.startswith('"') and arg.endswith('"'):
                            arg = arg[1:-1]
                        if arg:  # Ignore empty arguments
                            distinfo[var] = arg.strip()
        except IOError as msg:
            print('Unable to open ' + etc_lsb_release + ':', str(msg),
                  file=sys.stderr)

    return distinfo


def get_distro_information():
    lsbinfo = get_lsb_information()
    # OS is only used inside guess_debian_release anyway
    for key in ('ID', 'RELEASE', 'CODENAME', 'DESCRIPTION',):
        if key not in lsbinfo:
            distinfo = guess_debian_release()
            distinfo.update(lsbinfo)
            return distinfo
    else:
        return lsbinfo


# STARTING OF REAL CODE

PYTHON34_HOME = '/opt/python34'

PYTHON34_DOWNLOAD_URL = 'https://www.python.org/ftp/python/' \
                        '3.4.3/Python-3.4.3.tar.xz'

PYTHON34_MD5_CHECKSUM = '7d092d1bba6e17f0d9bd21b49e441dd5'

DEPS = {}

DEPS['Debian'] = {}

DEPS['Debian']['7.8'] = ('build-essential',
                         'openssl', 'libssl-dev',
                         'libsqlite3-0', 'libsqlite3-dev',
                         'libbz2-1.0', 'libbz2-dev',
                         'libdb5.1', 'libdb-dev',
                         'libgdbm3', 'libgdbm-dev',
                         'liblzma5', 'liblzma-dev',
                         'libncurses5', 'libncurses5-dev',
                         'libreadline6', 'libreadline6-dev')

DEPS['Ubuntu'] = {}

DEPS['Ubuntu']['13.10'] = ('build-essential',
                           'openssl', 'libssl-dev',
                           'libsqlite3-0', 'libsqlite3-dev',
                           'libbz2-1.0', 'libbz2-dev',
                           'libdb5.1', 'libdb-dev',
                           'libgdbm3', 'libgdbm-dev',
                           'liblzma5', 'liblzma-dev',
                           'libncurses5', 'libncurses5-dev',
                           'libreadline6', 'libreadline6-dev')

DEPS['Ubuntu']['14.04'] = ('build-essential',
                           'openssl', 'libssl-dev',
                           'libreadline6-dev',
                           'zlib1g-dev', 'libbz2-dev', 'liblzma-dev',
                           'libgdbm-dev', 'libdb-dev', 'libssl-dev',
                           'libexpat1-dev', 'libmpdec-dev',
                           'libbluetooth-dev', 'locales',
                           'libsqlite3-dev', 'libffi-dev',
                           'libgpm2', 'mime-support', 'netbase', 'bzip2',
                           'net-tools', 'xvfb', 'xauth')


def user_home():
    return os.path.expanduser('~')


def users_home():
    names = user_home().split(os.path.sep)
    if names[-1] == os.environ.get('USER'):
        names = names[:-1]
    return os.path.sep.join(['.'] + names)


def source_directory():
    return os.path.sep.join((user_home(), '.python34'))


def build_directory():
    return os.path.sep.join((user_home(), '.python34-build'))


def md5sum(filename, block_size=2**16):
    md5 = hashlib.md5()
    try:
        file = open(filename, 'rb')
        while 1:
            data = file.read(block_size)
            if not data:
                break
            md5.update(data)
    except IOError:
        print('Error calculating MD5 sum for file {}'.format(filename))
        return None
    except:
        return None
    return md5.hexdigest()


def get_source_filename():
    return PYTHON34_DOWNLOAD_URL.split(os.path.sep)[-1]


def get_source_filepath():
    return os.path.sep.join((source_directory(), get_source_filename()))


def ensure_source_downloaded(turn=3):
    home = users_home()
    if not os.path.exists(home):
        print('User home directory: {} not found'.format(home))
        exit(1)

    sdir = source_directory()
    if not os.path.exists(sdir):
        os.mkdir(sdir)
        print('Created directory {}'.format(sdir))

    sfile = get_source_filepath()
    if not os.path.exists(sfile):
        print('Downloading source to {}...'.format(sfile), end='')
        sys.stdout.flush()

        with urllib.request.urlopen(PYTHON34_DOWNLOAD_URL) as response, \
                open(sfile, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

        print('done')

    checksum = md5sum(sfile)
    if checksum != PYTHON34_MD5_CHECKSUM:
        os.unlink(sfile)
        if turn > 0:
            print('MD5 sum failed. Trying again...')
            ensure_source_downloaded(turn-1)
        else:
            print('MD5 sum failed. Check you internet connection!')
            exit(1)


def get_lsb_release():
    return get_distro_information()


def ensure_user_root():
    if pwd.getpwnam(os.environ.get('USER')).pw_uid != 0:
        print('Must be root. What about sudo?')
        exit(1)


def ensure_distribution_supported():
    lsb = get_lsb_release()
    dist = DEPS.get(lsb['ID'], None)
    if dist:
        dist_rel = dist.get(lsb['RELEASE'], None)
        if dist_rel:
            return dist_rel
        else:
            print('This release of {} is not supported'.format(dist))
            exit(1)
    else:
        print('This Linux Distribution is not supported')
        exit(1)


def ensure_packages_installed(packages, install_packages=True):
    missing = []

    with open('/dev/null', 'w+') as devnull:
        for pkg in packages:
            status = call(['dpkg', '-s', pkg],
                          timeout=5, stdout=devnull, stderr=devnull)
            if status != 0:
                missing.append(pkg)

    if missing:
        if install_packages:
            for pkg in missing:
                status = call(['apt-get', 'install', '-y', pkg], timeout=30)
                if status != 0:
                    print('Could not install {} package'.format(pkg))
                    exit(1)
            ensure_packages_installed(packages, False)
        else:
            print('Missing packages: {}'.format(','.join(missing)))
            exit(1)


def get_extracted_dir():
    src_fname = get_source_filename()
    dir_fname = '.'.join(src_fname.split(os.sep)[-1].split('.')[:-2])
    return os.sep.join((build_directory(), dir_fname))


def ensure_python34_built(install_directory):
    build_dir = build_directory()
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)

    if os.path.exists(install_directory):
        shutil.rmtree(install_directory)

    log_filepath = os.path.sep.join((build_dir, 'errors.log'))

    if not os.path.exists(build_dir):
        os.mkdir(build_dir)

        # extract source

        sfile = get_source_filepath()
        print('Extracting {}..'.format(sfile), end='')
        sys.stdout.flush()

        with open(log_filepath, 'w+') as output:

            status = call(['tar', 'xf', sfile, '-C', build_dir],
                          timeout=10, stdout=output, stderr=output)

            if status != 0:
                print('error')
                print('Could not extract files to {}'.format(build_dir))
                exit(1)

        print('done')

        # compile

        src_dir = get_extracted_dir()
        os.chdir(src_dir)

        print('Configuring sources...', end='')
        sys.stdout.flush()

        with open(log_filepath, 'w+') as output:
            status = call(['./configure',
                           '--prefix={}'.format(install_directory),
                           '--disable-ipv6',
                           '--with-dbmliborder=bdb:gdbm'],
                          timeout=300, stdout=output, stderr=output)

        if status != 0:
            print('error')
            print('Could not configure python sources in {}'.format(src_dir))
            exit(1)
        else:
            print('done')

        print('Compiling sources...', end='')
        sys.stdout.flush()

        with open(log_filepath, 'a') as output:
            status = call(['make'], timeout=300, stdout=output, stderr=output)

        if status != 0:
            print('error')
            print('Could not compile python sources in {}'.format(src_dir))
            exit(1)
        else:
            print('done')

        with open(log_filepath, 'a') as output:
            status = call(['make', 'install'],
                          timeout=300, stdout=output, stderr=output)

        if status != 0:
            print('error')
            print('Could not install python3 in {}'.format(src_dir))
            exit(1)
        else:
            print('done')
    else:
        print('Could not empty {} directory'.format(build_dir))
        exit(1)


def main(install_directory):
    ensure_user_root()
    ensure_source_downloaded()
    packages_needed = ensure_distribution_supported()
    ensure_packages_installed(packages_needed)
    ensure_python34_built(install_directory)
    exit(0)


if __name__ == "__main__":
    parser = \
        argparse.ArgumentParser(prog='py34-install',
                                description='Compile and install Python3.4')

    parser.add_argument('--install-directory',
                        type=str,
                        default=PYTHON34_HOME,
                        help='(default: {})'.format(PYTHON34_HOME))

    args = parser.parse_args()
    main(args.install_directory)
