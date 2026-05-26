from setuptools import setup, find_packages

setup(
    name="causetrace",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "gitpython",
        "python-dotenv",
        "requests",
    ],
    entry_points={
        "console_scripts": [
            "causetrace = main:main",
        ],
    },
)
