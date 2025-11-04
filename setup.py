from setuptools import setup, find_packages

setup(
    name="oncology-agents",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        # databricks-sdk and pyspark are already available on Databricks clusters
        # No external dependencies needed - our agents use only built-in libraries
    ],
    author="Databricks",
    description="Multi-Agent System for Oncology Document Processing",
)
