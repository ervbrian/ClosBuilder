import argparse
import docker
import json
import sys
from time import sleep
from typing import Dict, List

from docker.client import DockerClient


def parse_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--input_json",
        required=True,
        help="Input JSON containing GNS3 topology details",
    )
    parser.add_argument(
        "-dc",
        "--docker_client",
        required=True,
        help="Docker client URL (Eg. tcp://10.0.0.3:2375)",
    )
    parser.add_argument(
        "-c",
        "--config_dir",
        required=True,
        help="Absolute path to directory containing network device configurations",
    )
    parser.add_argument(
        "-s",
        "--shift_traffic",
        action="store_true",
        default=False,
        help="Shift traffic away from devices before pushing configuration",
    )
    parser.add_argument(
        "-init",
        "--initial_push",
        action="store_true",
        default=False,
        help="Use when device is brand new to the network",
    )
    parser.add_argument(
        "-ch",
        "--check_commands",
        nargs="+",
        default=[],
        help="List of validation commands to execute after configuration push",
    )

    return parser.parse_args()


def generate_router_container_map(gns_json: str) -> Dict:
    with open(gns_json, "r") as f:
        topology = json.load(f)

        nodes = [node for node in topology["topology"]["nodes"]]
        router_container_map = {
            router["name"]: router["properties"]["container_id"]
            for router in nodes
            if "frr" in router["properties"]["image"]
        }

    return router_container_map


def shift_ospf(router: str, direction: str, container_client: DockerClient) -> None:
    if direction == "away":
        shift_config = "vtysh -c 'conf t' -c 'router ospf' -c 'max-metric router-lsa administrative' -c 'end' -c 'write file'"
        message = f"Applying OSPF max-metric to shift traffic away from {router} and pausing for 90 seconds for convergence"
    else:
        shift_config = "vtysh -c 'conf t' -c 'router ospf' -c 'no max-metric router-lsa administrative' -c 'end' -c 'write file'"
        message = f"Removing OSPF max-metric to shift traffic back to {router} and pausing for 90 seconds for convergence"

    print(message)
    container_client.exec_run(cmd=["sh", "-c", shift_config])
    sleep(90)


def stage_frr_configs(router: str, frr_config, container_client: DockerClient) -> None:
    """Deploy FRR configurations to router"""
    print(f"Staging frr.conf on {router}")
    with open(frr_config, "r") as f:
        config = f.read()

    # Convert to byte string before executing echo command on container
    encoded_config = bytes(config, "utf-8")

    # Convert byte string back to UTF8 before dumping to frr.conf
    container_client.exec_run(
        cmd=[
            "sh",
            "-c",
            f"echo {encoded_config} | iconv -f utf8 >> /etc/frr/frr.conf",
        ]
    )


def overwrite_vtysh_configs(router: str, countainer_client: DockerClient) -> None:
    print(f"Overwriting vtysh.conf on {router}")
    countainer_client.exec_run(
        cmd=[
            "sh",
            "-c",
            "rm /etc/frr/vtysh.conf && touch /etc/frr/vtysh.conf && chown frr:frr /etc/frr/vtysh.conf",
        ]
    )


def verify_router_connections(client: DockerClient, router_container_map: Dict) -> bool:
    print(f"Verifying connection to Docker containers for all network devices")
    verification_succeeded = True
    for router, container in router_container_map.items():
        try:
            connection_status = client.containers.get(container_id=container).status
            assert connection_status == "running"
            print(f"Connection verification for {router} SUCCEEDED")
        except Exception as e:
            print(f"Connection verification for {router} FAILED")
            verification_succeeded = False

    return verification_succeeded


def run_check(container: DockerClient, check_command: str) -> None:
    """Execute a post-deployment check on network device
    Results are decoded and printed to stdout"""
    print(f"Running the following check as per deployment options:\n{check_command}")
    results = container.exec_run(cmd=check_command).output.decode("utf-8")
    print(results)


def deploy_config(
    router_container_map: Dict,
    docker_client: docker.DockerClient,
    shift_traffic: bool = False,
    initial_push: bool = False,
    check_commands: List[str] = None,
):
    print(f"## Starting deployment to {len(router_container_map)} devices ## \n")
    for router, container_id in router_container_map.items():
        container = docker_client.containers.get(container_id=container_id)

        if initial_push:
            overwrite_vtysh_configs(router=router, countainer_client=container)

        if shift_traffic:
            shift_ospf(router=router, direction="away", container_client=container)

        # Backup current FRR config
        print(f"Backing up frr.conf on {router} as frr.conf.backup")
        container.exec_run(
            cmd=["sh", "-c", "mv /etc/frr/frr.conf /etc/frr/frr.conf.backup"]
        )

        # Write new configs
        frr_config = f"/tmp/output/{router}_frr.conf"
        stage_frr_configs(
            router=router, frr_config=frr_config, container_client=container
        )

        # Update permissions
        container.exec_run(cmd=["sh", "-c", "chown frr:frr /etc/frr/frr.conf"])

        # Restart FRR service
        print(f"Restarting FRR service on {router}")
        container.exec_run(cmd=["sh", "-c", "service frr restart"])

        # Run verification check
        if check_commands:
            sleep(10)  # Allow some time for FRR service to stabilize
            for command in check_commands:
                run_check(container=container, check_command=command)

        # Pause for convergence if shifting is enabled
        if shift_traffic:
            print("Pausing 90 seconds for convergence")
            sleep(90)

        print(f"Deployment to {router} completed successfully\n")


if __name__ == "__main__":
    args = parse_args()

    # Generate router to container_id map
    router_container_map = generate_router_container_map(gns_json=args.input_json)

    # Establish connection to Docker client
    docker_client = docker.DockerClient(base_url=args.docker_client)

    # Verify connection to each docker container
    if not verify_router_connections(
        client=docker_client, router_container_map=router_container_map
    ):
        print(
            "Please verify all network devices are running in GNS3. Aborting deployment"
        )
        sys.exit(1)

    # Deploy configurations
    deploy_config(
        router_container_map=router_container_map,
        shift_traffic=args.shift_traffic,
        initial_push=args.initial_push,
        docker_client=docker_client,
        check_commands=args.check_commands,
    )
