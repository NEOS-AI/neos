import argparse
import subprocess
import sys
import os

parser = argparse.ArgumentParser()

parser.add_argument("--ml", action="store_true", help="Flag to configure whether everything for machine learning should also be setup")

args = parser.parse_args()

necesarry_packages = [
    "pandas",
]

ml_packages = [
    "safetensors",
    "datasets",
    "torch",
    "transformers",
]

packages_to_install = necesarry_packages

if args.ml:
    packages_to_install += ml_packages

try:
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade"] + packages_to_install)
except Exception:
    subprocess.run(["python3", "-m", "pip", "install", "--upgrade"] + packages_to_install)

# old_dir = os.getcwd()
# os.chdir("crates/client-wasm")
# subprocess.run(["wasm-pack", "build", "--target", "web"])
# os.chdir(old_dir)


if args.ml:
    subprocess.run(["python3 scripts/export_crossencoder.py"])
    subprocess.run(["python3 scripts/export_dual_encoder.py"])
