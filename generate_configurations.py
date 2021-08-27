import argparse
import os
import sys
import yaml
from typing import Dict
from models.clos import TwoTierClos, InvalidArchitecture


MODEL_INVOCATION_MAP = {"TwoTierClos": TwoTierClos}


def parse_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--input_file",
        help="Input YAML containing network implementation details",
        required=True,
    )
    parser.add_argument(
        "-g",
        "--generate",
        action="store_true",
        help="Generate device configurations after modeling netwwork architecture",
        required=False,
    )
    parser.add_argument(
        "-o",
        "--output_dir",
        help="Absolute path to directory where configurations will be written",
        required=False,
    )

    return parser.parse_args()


def parse_input_yaml(filename: str) -> Dict:
    """Parse input YAML for network architecture details
    Return dictionary that will be used for model creation"""
    with open(filename, "r") as f:
        network_details = yaml.load(f, Loader=yaml.Loader)

    return network_details


if __name__ == "__main__":
    args = parse_args()

    # Parse input YAML
    network_details = parse_input_yaml(filename=args.input_file)

    # Determine modeling class
    architecture = network_details.get("architecture")

    # Generate modeling datastructure based on input YAML info
    model_class = MODEL_INVOCATION_MAP.get(architecture)

    if model_class:
        architecture_model = model_class(
            width=network_details.get("width"),
            device_interface_count=network_details.get("device_interface_count"),
            internal_supernet=network_details.get("internal_supernet"),
            loopback_supernet=network_details.get("loopback_supernet"),
            external_networks=network_details.get("external_networks"),
        )
    else:
        raise InvalidArchitecture(
            f"Architecture unsupported: {architecture}. Please choose from: {list(MODEL_INVOCATION_MAP)}"
        )

    # Generate configuration files based on model
    if args.generate:
        if not os.path.exists(args.output_dir):
            os.mkdir(args.output_dir)

        architecture_model.render(output_dir=args.output_dir)
