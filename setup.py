from setuptools import setup, find_packages

package_name = "pibble"
version_major = "0"
version_minor = "4"
version_patch = "0"

install_requires = [
    "bcrypt>=4.0,<4.1",
    "boto3>=1.26,<2.0",
    "chardet>=5.1,<5.2",
    "click>=8.0,<9.0",
    "configparser>=5.3,<5.4",
    "gunicorn>=20.0,<21.0",
    "jinja2>=3.1,<3.2",
    "lxml>=4.9,<5.0",
    "mimeparse>=0.1",
    "mypy>=1.2,<1.3",
    "openpyxl>=3.1,<4.0",
    "pandas>=2.0,<3.0",
    "paramiko>=3.1,<4.0",
    "pycryptodome>=3.17,<4.0",
    "pyftpdlib>=1.5,<2.0",
    "pyopenssl>=23.1,<24.0",
    "pyyaml>=6.0,<7.0",
    "requests>=2.28,<3.0",
    "requests-oauthlib>=1.3,<2.0",
    "semantic-version>=2.10,<3.0",
    "sqlalchemy>=1.4,<2.0",
    "sshpubkeys>=3.3,<4.0",
    "termcolor>=2.2,<3.0",
    "webob>=1.8,<2.0",
    "werkzeug>=2.2,<3.0",
    "wsgitypes>=0.0.4",
    "xlrd>=2.0,<3.0",
    "zeep>=4.2,<5.0",
]

extras_require = {
    "mysql": ["mysqlclient>=2.1,<2.2"],
    "postgresql": ["psycopg2-binary>=2.9,<3.0"],
    "mssql": ["pyodbc>=4.0,<5.0", "sqlalchemy-pyodbc-mssql>=0.1"],
    "thrift": ["thrift>=0.16,<1.0"],
    "grpc": ["grpcio<1.49", "grpcio-tools<1.49"],
    "browser": ["selenium>=4.8,<5.0"],
    "imaging": ["pdf2image>=1.16,<2.0", "pillow>=9.5,<10.0", "psd-tools>=1.9,<2.0"],
    "build": [
        "sphinx",
        "sphinx_rtd_theme",
        "types-PyYAML",
        "types-chardet",
        "types-requests",
        "types-termcolor",
        "types-pytz",
        "types-python-dateutil",
        "types-protobuf",
        "types-paramiko",
        "types-oauthlib",
        "types-openpyxl==3.0.0",
        "types-urllib3<1.27",
        "importchecker",
    ],
}

extras_require["all"] = [
    package for package_list in extras_require.values() for package in package_list
]

setup(
    name=package_name,
    author="Benjamin Paine",
    author_email="painebenjamin@gmail.com",
    version=f"{version_major}.{version_minor}.{version_patch}",
    packages=find_packages("."),
    package_data={"pibble": []},
    license="GPLv3",
    long_description="A framework for developing webapps quickly and easily using Python",
    install_requires=install_requires,
    extras_require=extras_require,
)
