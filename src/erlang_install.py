#!/usr/bin/env python
# -o- coding: utf-8 -o-
'''
Created on 26/09/2013
@author: Carlo Pires <carlopires@gmail.com>
'''
import os, argparse
from subprocess import call, check_output, Popen, PIPE

ERLANG_DOWNLOAD_URL='http://www.erlang.org/download'
ERLANG_RELEASE='R15B02'
ERLANG_DIRECTORY='erlang'

def user_home():
    return os.path.expanduser('~')

def users_home():
    names = user_home().split(os.path.sep)
    if names[-1] == os.environ.get('USER'):
        names = names[:-1]
    return os.path.sep.join(names)

def erlang_home():
    return os.path.sep.join((user_home(), ERLANG_DIRECTORY))

def erlang_release_home(release):
    return os.path.sep.join((erlang_home(), release.lower()))

def main(erlang_release, erlang_directory):
    home = users_home()
    
    if not os.path.exists(home):
        print('User home directory ({}) not found '.format(home))
        exit(1)
      
    ehome = erlang_home()
        
    if not os.path.exists(ehome):
        os.mkdir(ehome)
        print('Created erlang home directory: {}'.format(ehome))
        
    print('REL: ', erlang_release, '\n', 'DIR: ', erlang_directory)
    
if __name__ == "__main__":
    ehome = erlang_release_home(ERLANG_RELEASE)
    
    parser = argparse.ArgumentParser(prog='einstall', description='Compile and install erlang')
    parser.add_argument('--erlang-release', type=str, default=ERLANG_RELEASE, help='(default: {})'.format(ERLANG_RELEASE))
    parser.add_argument('--erlang-directory', type=str, default=ehome, help='(default: {})'.format(ehome))
    
    args = parser.parse_args()
    main(args.erlang_release, args.erlang_directory)
    
