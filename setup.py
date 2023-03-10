import configparser
from pathlib import Path

from setuptools import find_packages, setup

import dtf


def get_package_dependencies_from_pipfile():
    pipfile_filepath = Path(__file__).resolve().parent / "Pipfile"
    assert pipfile_filepath.exists()
    config = configparser.ConfigParser()
    config.read(str(pipfile_filepath))

    def clean_quotes(value):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value

    deps = []
    for package_set in zip(config["packages"], config["packages"].values()):
        required_package, required_version = package_set
        required_package = clean_quotes(required_package)
        required_version = clean_quotes(required_version)
        if required_version != "*":
            required_package = f"{required_package}{required_version}"
        deps.append(required_package)
    return deps


setup(
    name="dtf",
    version=dtf.__version__,
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    data_files=[
        ("", ["README.md"]),
        ("", ["Pipfile"]),
        ("", ["Pipfile.lock"]),
    ],
    url="",
    license="BSD license",
    author="monkut",
    author_email="shane.cousins@gmail.com",
    description="Collect target reaction videos from youtube and create playlists",
    install_requires=get_package_dependencies_from_pipfile(),
)
