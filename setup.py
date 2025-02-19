import os
from setuptools import setup, find_packages

package_name = "fruition"
version_major = "0"
version_minor = "9"
version_patch = "2"

install_requires = [
    "bcrypt>=4.0,<4.1",
    "chardet>=5.0,<5.2",
    "click>=8.0,<9.0",
    "configparser>=5.2,<5.4",
    "jinja2>=3.0,<3.2",
    "mimeparse>=0.1",
    "pandas>=2.0,<3.0",
    "pycryptodome>=3.17,<4.0",
    "pyopenssl>=23.1,<24.0",
    "pyyaml>=6.0,<7.0",
    "requests>=2.12,<3.0",
    "requests-oauthlib>=1.3,<2.0",
    "semantic-version>=2.10,<3.0",
    "sqlalchemy>=1.1,<2.0",
    "sshpubkeys>=3.3,<4.0",
    "termcolor>=1.0,<3.0",
    "webob>=1.8,<2.0",
    "zeep>=4.2,<5.0",
    "paramiko>=3.1,<4.0",
    "pillow>=9.0,<11.0",
]

extras_require = {
    "mysql": ["mysqlclient>=2.1,<2.2"],
    "postgresql": ["psycopg2-binary>=2.9,<3.0"],
    "mssql": ["pyodbc>=5.0,<6.0", "sqlalchemy-pyodbc-mssql>=0.1"],
    "thrift": ["thrift>=0.16,<1.0"],
    "grpc": ["grpcio", "grpcio-tools"],
    "browser": ["selenium>=4.8,<5.0"],
    "imaging": ["pdf2image>=1.16,<2.0", "pillow>=10.0,<11.0", "psd-tools>=1.9,<2.0"],
    "cherrypy": ["cherrypy>=18.8,<19.0"],
    "gunicorn": ["gunicorn>=20.0,<21.0"],
    "werkzeug": ["werkzeug>=2.2,<3.0"],
    "excel": ["openpyxl>=3.1,<4.0", "xlrd>=2.0,<3.0"],
    "aws": ["boto3>=1.26,<2.0"],
    "ftp": ["pyftpdlib>=1.5,<2.0"],
    "xml": ["lxml>=4.9,<5.0"],
    "build": [
        "sphinx>=6.2,<6.3",
        "sphinx-rtd-theme>=1.2,<1.3",
        "types-PyYAML>=6.0.12,<6.1",
        "types-chardet>=5.0.4,<6.0",
        "types-requests>=2.29,<3.0",
        "types-termcolor>=1.1.6,<1.2",
        "types-pytz>=2023.3",
        "types-python-dateutil>=2.8.19,<3.0",
        "types-protobuf>=4.22,<5.0",
        "types-pillow>=10.0,<11.0",
        "types-paramiko>=3.0,<4.0",
        "types-oauthlib>=3.2,<4.0",
        "types-openpyxl==3.0.0",
        "types-urllib3<1.27",
        "importchecker>=2.0,<3.0",
        "black>=23.3,<24.0",
        "twine>=4.0,<5.0",
        "mypy>=1.2,<1.3",
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
    package_data={"fruition": ["py.typed"]},
    license="gpl-3.0",
    url="https://github.com/painebenjamin/fruition",
    description="A framework for developing webapps quickly and easily using Python, SQLAlchemy, and Jinja2. Supports numerous protocols, databases, and web drivers.",
    long_description=open("README.md", "r", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    entry_points={
        "console_scripts": ["fruition = fruition.__main__:main"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    install_requires=install_requires,
    extras_require=extras_require,
)
