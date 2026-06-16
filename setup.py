from setuptools import find_packages, setup


setup(
    name="xhs-auto-publisher",
    version="1.0.0",
    author="Claw",
    description="小红书自动发布桌面工具",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "SQLAlchemy>=2.0.0",
        "requests>=2.31.0",
        "httpx>=0.25.0",
        "Pillow>=10.0.0",
    ],
    entry_points={
        "console_scripts": [
            "xhs-publisher=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Internet :: WWW/HTTP",
    ],
)
