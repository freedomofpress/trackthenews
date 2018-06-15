import sys
if sys.version_info < (3,0):
    sys.exit('Sorry, trackthenews only runs on Python 3+')

from setuptools import setup, find_packages

with open('requirements.txt') as f:
    reqs = f.read.split()

with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='trackthenews',
    version='0.1.0',
    description='Monitor RSS feeds for keywords and act on matching results. A special project of the Freedom of the Press Foundation.',
    long_description=readme,
    reqs=reqs,
    author='Parker Higgins',
    author_email='parker@freedom.press',
    url='https://github.com/freedomofpress/trackthenews',
    license=license,
    packages=find_packages(exclude=('ttn-config'))
)
