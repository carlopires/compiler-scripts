#!/usr/bin/env python3
'''
Created on 26/09/2013
@author: Carlo Pires <carlopires@gmail.com>
'''
import os, sys, argparse
import urllib.request
import shutil
import hashlib
import pwd
from subprocess import call, check_output, Popen, PIPE

PYTHON34_HOME = '/opt/python34'

PYTHON34_DOWNLOAD_URL='http://python.org/ftp/python/3.4.0/Python-3.4.0a2.tar.xz'
PYTHON34_MD5_CHECKSUM='36c941d1466730a70d0ae92442cc3fcf'

DEPS = {}
DEPS['Ubuntu'] = {}

DEPS['Ubuntu']['13.10'] = ('build-essential',  
    'libsqlite3-0', 'libsqlite3-dev',
    'libbz2-1.0', 'libbz2-dev',
    'libdb5.1', 'libdb-dev',
    'libgdbm3', 'libgdbm-dev',
    'liblzma5', 'liblzma-dev',
    'libncurses5', 'libncurses5-dev',
    'libreadline6', 'libreadline6-dev')

def user_home():
    return os.path.expanduser('~')

def users_home():
    names = user_home().split(os.path.sep)
    if names[-1] == os.environ.get('USER'):
        names = names[:-1]
    return os.path.sep.join(names)

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
        print('User home directory ({}) not found'.format(home))
        exit(1)
    
    sdir = source_directory()
    if not os.path.exists(sdir):
        os.mkdir(sdir)
        print('Created directory {}'.format(sdir))
    
    sfile = get_source_filepath()
    if not os.path.exists(sfile):
        print('Downloading source to {}...'.format(sfile), end='') ; sys.stdout.flush()
        with urllib.request.urlopen(PYTHON34_DOWNLOAD_URL) as response, open(sfile, 'wb') as out_file:
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
    return dict([line[:-1].split('=') for line in open('/etc/lsb-release','r').readlines()]) 

def ensure_user_root():
    if pwd.getpwnam(os.environ.get('USER')).pw_uid != 0:
        print('Must be root. What about sudo?')
        exit(1)

def ensure_distribution_supported():
    lsb = get_lsb_release()
    dist = DEPS.get(lsb['DISTRIB_ID'], None)
    if dist:
        dist_rel = dist.get(lsb['DISTRIB_RELEASE'], None)
        if dist_rel:
            return dist_rel
        else:
            print('This release of {} is not supported'.format(lsb['DISTRIB_ID']))
            exit(1)
    else:
        print('This Linux Distribution is not supported')
        exit(1)

def ensure_packages_installed(packages, install_packages=True):
    missing = []
    
    with open('/dev/null', 'w+') as devnull:
        for pkg in packages:
            status = call(['dpkg', '-s', pkg], timeout=5, stdout=devnull, stderr=devnull)
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
            
def ensure_python34_built(install_directory):
    build_dir = build_directory()
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
        
    log_filepath = os.path.sep.join((build_dir, 'errors.log'))
        
    if not os.path.exists(build_dir):
        os.mkdir(build_dir)
        
        # extract source
        
        sfile = get_source_filepath()
        print('Extracting {}..'.format(sfile), end='') ; sys.stdout.flush()
        
        with open('/dev/null', 'w+') as devnull:
            status = call(['tar', 'xf', sfile, '-C', build_dir], timeout=10, stdout=devnull, stderr=devnull)
            if status != 0:
                print('error')
                print('Could not extract files to {}'.format(build_dir))
                exit(1)
                
        print('done')
        
        # compile
        
        dir_name = '.'.join(get_source_filename().split('.')[:-2])
        src_dir = os.path.sep.join((build_dir, dir_name))
        os.chdir(src_dir)
        
        print('Configuring sources...', end='') ; sys.stdout.flush()
        
        with open(log_filepath, 'w+') as output:
            status = call(['./configure',
                '--prefix={}'.format(install_directory), 
                '--disable-ipv6', '--with-dbmliborder=bdb:gdbm'], timeout=300, stdout=output, stderr=output)
            
        if status != 0:
            print('error')
            print('Could not configure python sources in {}'.format(src_dir))
            exit(1)
        else:
            print('done')

        print('Compiling sources...', end='') ; sys.stdout.flush()

        with open(log_filepath, 'a') as output:
            status = call(['make'], timeout=300, stdout=output, stderr=output)
            
        if status != 0:
            print('error')
            print('Could not compile python sources in {}'.format(src_dir))
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
    parser = argparse.ArgumentParser(prog='py34-install', description='Compile and install Python3.4')
    parser.add_argument('--install-directory', type=str, default=PYTHON34_HOME, help='(default: {})'.format(PYTHON34_HOME))
    
    args = parser.parse_args()
    main(args.install_directory)
    
