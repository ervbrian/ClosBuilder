from render.frr_render import generate_frr_configs
from ipaddress import ip_network
from typing import Dict, List


class InsufficientIpSubnets(Exception):
    """This exception is raised when subnets have been exhausted from a given supernet"""


class InvalidArchitecture(Exception):
    """This exception is raised when an unsupported architecture is defined in an input YAML"""


class Interface:
    """This class represents an interface on a nework device"""

    def __init__(
        self,
        interface: str,
        ip_address: str = "",
        description: str = "",
        allocated: bool = False,
    ) -> None:
        self.interface = interface
        self.ip_address = ip_address
        self.description = description
        self.allocated = allocated
        self.ospf_enabled = False


class Device:
    """This class represents a network router with interfaces and routing protocol attributes"""

    def __init__(self, hostname: str, interface_count: int, loopback: str) -> None:
        self.hostname = hostname
        self.router_id = str(loopback.hosts()[0])
        self.__interface_names = [f"eth{i}" for i in range(interface_count)]
        self.interfaces = [
            Interface(interface=interface) for interface in self.__interface_names
        ]
        self.interfaces.append(
            Interface(
                interface="lo",
                ip_address=loopback,
                allocated=True,
                description="loopback used for RID",
            )
        )
        self.ospf = OspfInstance(instance_id=0, networks=[loopback])
        self.bgp = BgpInstance(asn=65000, neighbors=[], networks=[])

    def next_available_interface(self) -> Interface:
        """Iterate through each interface until an unallocated interface is found
        Set allocated to True and return Interface object"""
        for interface in self.interfaces:
            if not interface.allocated:
                interface.allocated = True
                return interface


class StaticRoute:
    """This class represents a static route that can be added to a Device"""

    def __init__(self, cidr: str, next_hop: str, description: str) -> None:
        self.cidr = cidr
        self.next_hop = next_hop
        self.description = description


class OspfInstance:
    """This class represents an OSPF instance
    Each network and its corresponding area ID will be added to the OSPF LSDB"""

    def __init__(self, instance_id: int, networks: List[str]) -> None:
        self.instance_id = instance_id
        self.networks = networks


class BgpInstance:
    """This class represents a BGP routing instance on a network Device"""

    def __init__(self, asn: int, neighbors: List[dict], networks: List[str]) -> None:
        self.asn = asn
        self.neighbors = neighbors
        self.networks = networks


class ClosTier:
    """This class represents a tier or layer of network Devices in a Clos architecture"""

    def __init__(self, tier_number: int, width: int, loopback_subnets: List) -> None:
        self.width = width
        self.__device_names: List[str] = [
            f"t{str(tier_number)}-r{i}" for i in range(1, width + 1)
        ]
        self.__loopback_subnets = loopback_subnets
        self.devices: List[Device] = self.initialize_devices()

    def initialize_devices(self) -> List[Device]:
        devices = []
        for hostname in self.__device_names:
            loopback_ip = self.allocate_loopback()

            devices.append(
                Device(
                    hostname=hostname,
                    interface_count=self.width * 2,
                    loopback=loopback_ip,
                )
            )

        return devices

    def allocate_loopback(self):
        try:
            return self.__loopback_subnets.pop(0)
        except:
            raise InsufficientIpSubnets("Could not allocate all loopback IPs required")


class TwoTierClos:
    """This class represents a Clos architecture with t1 and t2 layers"""

    def __init__(
        self,
        width: int,
        internal_supernet: str,
        loopback_supernet: str,
        external_networks: Dict,
    ) -> None:
        self.connections: int = 0
        self.width = width
        self.internal_subnets = list(
            ip_network(internal_supernet).subnets(new_prefix=31)
        )
        self.loopbacks = list(ip_network(loopback_supernet).subnets(new_prefix=32))
        self.t1 = ClosTier(tier_number=1, width=width, loopback_subnets=self.loopbacks)
        self.t2 = ClosTier(tier_number=2, width=width, loopback_subnets=self.loopbacks)
        self.external_networks = external_networks
        self.add_internal_connections()
        self.add_bgp_peers()
        self.add_external_networks()
        self.show_architecture_statistics()

    def show_architecture_statistics(self):
        print()
        print(f"#### Architecture Stats ####")
        print(f"Clos Width: {self.width}")
        print(f"Total Internal Connections: {self.connections}")
        print(f"Total Unused Internal Subnets: {len(self.internal_subnets)}")
        print(f"Total Unused Loopbacks: {len(self.loopbacks)}")
        print(
            f"Total CLient Facing Ports: {(len(self.t1.devices[0].interfaces) - 1) * len(self.t1.devices) // 2}"
        )
        print()

    def allocate_ptp_subnet(self):
        try:
            return self.internal_subnets.pop(0)
        except Exception:
            raise InsufficientIpSubnets("Could not allocate all PTP subnets required")

    def add_internal_connections(self) -> None:
        """Connects all t1 devices to all t2 devices"""

        for t2_device in self.t2.devices:
            for t1_device in self.t1.devices:
                # Allocate next availbe interface on t1 and t2 devices
                t2_interface = t2_device.next_available_interface()
                t1_interface = t1_device.next_available_interface()

                # Update interface descriptions
                t2_interface.description = f"{t2_device.hostname} {t2_interface.interface} -- {t1_interface.interface} {t1_device.hostname}"
                t1_interface.description = f"{t1_device.hostname} {t1_interface.interface} -- {t2_interface.interface} {t2_device.hostname}"

                # Fetch next available PTP subnet
                connection_subnet = self.allocate_ptp_subnet()

                # Update IP address on t1 and t2 interfaces
                t2_interface.ip_address = f"{list(connection_subnet.hosts())[0]}/31"
                t1_interface.ip_address = f"{list(connection_subnet.hosts())[1]}/31"

                # Trigger interface-level OSPF settings
                t2_interface.ospf_enabled = True
                t1_interface.ospf_enabled = True

                # Advertise PTP subnet in OSPF
                t2_device.ospf.networks.append(connection_subnet.with_prefixlen)
                t1_device.ospf.networks.append(connection_subnet.with_prefixlen)

                # Increment connection counter for internal links
                self.connections += 1

    def add_bgp_peers(self) -> None:
        t1_peers = [device.router_id for device in self.t1.devices]
        t2_peers = [device.router_id for device in self.t2.devices]

        # Update T1 devices' BGP instances
        for device in self.t1.devices:
            for peer in t2_peers:
                device.bgp.neighbors.append({"ip_address": peer, "peer_group": "T2"})

        # Update T2 devices' BGP instances
        for device in self.t2.devices:
            for peer in t1_peers:
                device.bgp.neighbors.append({"ip_address": peer, "peer_group": "T1"})

    def add_external_networks(self):
        for network in self.external_networks:
            for device in self.t1.devices:
                if device.hostname in self.external_networks[network]:
                    device.bgp.networks.append(network)

    def render(self, output_dir: str) -> None:
        for device in self.t1.devices + self.t2.devices:
            generate_frr_configs(device=device, output_dir=output_dir)
