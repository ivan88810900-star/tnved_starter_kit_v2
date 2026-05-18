from setuptools import setup

APP = ["src/eco_fee_app.py"]
DATA_FILES = ["data/eco_fee_rates_2026_2027.json"]

OPTIONS = {
    "argv_emulation": False,
    "packages": [],
    "resources": DATA_FILES,
    "plist": {
        "CFBundleName": "EcoFeeRF",
        "CFBundleDisplayName": "Эко-сбор РФ",
        "CFBundleIdentifier": "local.ecofee.rf",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
    },
}

setup(
    app=APP,
    data_files=[],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

