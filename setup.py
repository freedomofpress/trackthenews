from setuptools import setup, find_packages

with open('requirements.txt') as f:
    reqs = f.read().split()

with open('README') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='trackthenews',
    version='0.1.8.4',
    description='Monitor RSS feeds for keywords and act on matching results. A special project of the Freedom of the Press Foundation.',
    long_description=readme,
    install_requires=reqs,
    author='Parker Higgins',
    author_email='parker@freedom.press',
    url='https://github.com/freedomofpress/trackthenews',
    entry_points={
        'console_scripts': ['trackthenews=trackthenews:main']
    },
    package_data={
        'trackthenews': ['fonts/*']
    },
    include_package_data=True,
    license=license,
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6'],
    packages=find_packages(exclude=('ttnconfig',))
)
