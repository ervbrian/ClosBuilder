import os
from jinja2 import Template


def write_config_to_file(config: str, filename: str) -> None:
    print(f"Writing configurations to {filename}")
    with open(os.path.join(filename), "w") as f:
        f.write(config)


def generate_zebra_config(device, output_dir) -> str:
    template = """hostname {{ device.hostname}}
{% for interface in device.interfaces %}
{%- if interface.allocated %}
interface {{ interface.interface }}
  ip address {{ interface.ip_address }}
  description {{ interface.description }}
{% if interface.ospf_enabled %}
  ip ospf network point-to-point
  ip ospf hello-interval 1
  ip ospf dead-interval 4
  ip ospf cost 10
{% endif %}
{% endif %}
{%- endfor %}
"""

    jinja_template = Template(template)
    config = jinja_template.render(device=device)
    filename = os.path.join(output_dir, f"{device.hostname}_zebra.conf")
    write_config_to_file(config=config, filename=filename)

    return config


def generate_ospfd_config(device, output_dir) -> str:
    template = """router ospf
  max-metric router-lsa on-startup 60
{% for network in device.ospf.networks %}
  network {{ network }} area 0
{%- endfor %}

"""

    jinja_template = Template(template)
    config = jinja_template.render(device=device)
    filename = os.path.join(output_dir, f"{device.hostname}_ospfd.conf")
    write_config_to_file(config=config, filename=filename)

    return config


def generate_bgpd_config(device, output_dir) -> str:
    template = """ip prefix-list ANY permit 0.0.0.0/0 le 32
{%- if 't1' in device.hostname -%}
{%- set sequence_number = namespace(value=10) -%}
{% for network in device.bgp.networks %}
ip prefix-list EXTERNAL-NETWORKS seq {{ sequence_number.value }} permit {{ network }} le 24
{%- set sequence_number.value = sequence_number.value + 10 -%}
{%- endfor %}
ip prefix-list EXTERNAL-NETWORKS seq 1000 deny any
route-map RM-T2-OUT permit 10
 match ip address prefix-list EXTERNAL-NETWORKS
route-map RM-T2-IN permit 10
 match ip address prefix-list ANY
{% elif 't2' in device.hostname %}
route-map RM-T1-OUT permit 10
 match ip address prefix-list ANY
route-map RM-T1-IN permit 10
 match ip address prefix-list ANY
{% endif %}
router bgp {{ device.bgp.asn}}
  bgp router-id {{device.router_id}}
{% if 't1' in device.hostname %}
  neighbor T2 peer-group
  neighbor T2 update-source lo
  neighbor T2 remote-as 65000
  neighbor T2 description T2 Route-Reflector Peers
  neighbor T2 soft-reconfiguration inbound
  neighbor T2 route-map RM-T2-IN in
  neighbor T2 route-map RM-T2-OUT out
{% elif 't2' in device.hostname %}
  neighbor T1 peer-group
  neighbor T1 update-source lo
  neighbor T1 remote-as 65000
  neighbor T1 description T1 Route-Reflector Clients
  neighbor T1 soft-reconfiguration inbound
  neighbor T1 route-reflector-client
  neighbor T1 route-map RM-T1-IN in
  neighbor T1 route-map RM-T1-OUT out
{% endif %}
{% for neighbor in device.bgp.neighbors %}
  neighbor {{ neighbor['ip_address'] }} peer-group {{ neighbor['peer_group'] }}
{%- endfor %}
{% for network in device.bgp.networks %}
  network {{ network }}
{%- endfor %}
"""

    jinja_template = Template(template)
    config = jinja_template.render(device=device)
    filename = os.path.join(output_dir, f"{device.hostname}_bgpd.conf")
    write_config_to_file(config=config, filename=filename)

    return config


def integrate_frr_config(
    device, output_dir: str, zebra_config: str, ospfd_config: str, bgpd_config: str
) -> None:
    """Combine Zebra, ospfd and bpgd configs into an integrated FRR config file"""
    filename = os.path.join(output_dir, f"{device.hostname}_frr.conf")
    config = "\n".join([zebra_config, ospfd_config, bgpd_config])
    write_config_to_file(filename=filename, config=config)


def generate_frr_configs(device, output_dir):
    zebra_config = generate_zebra_config(device, output_dir)
    ospfd_config = generate_ospfd_config(device, output_dir)
    bgpd_config = generate_bgpd_config(device, output_dir)
    integrate_frr_config(device, output_dir, zebra_config, ospfd_config, bgpd_config)
