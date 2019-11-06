import setuptools
import os

own_dir = os.path.abspath(os.path.dirname(__file__))


def requirements():
    yield 'gardener-cicd-base'

    with open(os.path.join(own_dir, 'requirements.txt')) as f:
        for line in f.readlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            yield line


def modules():
    module_names = [
        os.path.basename(os.path.splitext(module)[0]) for module in
        os.scandir(path=own_dir)
        if module.is_file() and module.name.endswith('.py')
    ]

    # remove modules already contained in gardener-cicd-base
    module_names.remove('util')
    module_names.remove('ctx')


def packages():
    package_names = setuptools.find_packages()

    # remove packages already contained in gardener-cicd-base
    package_names.remove('ci')
    package_names.remove('model')


def version():
    with open(os.path.join(own_dir, 'ci', 'version')) as f:
        return f.read().strip()


setuptools.setup(
    name='gardener-cicd-libs',
    version=version(),
    description='Gardener CI/CD Libraries',
    python_requires='>=3.7.*',
    py_modules=modules(),
    packages=packages(),
    package_data={
        '':['*.mako'],
        'ci':['version'],
    },
    install_requires=list(requirements()),
    entry_points={
    },
)
