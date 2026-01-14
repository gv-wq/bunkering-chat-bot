from typing import List

from app.data.dto.searoute.SearoutePort import SearoutePort


def get_unique_ports(ports: List[SearoutePort]) -> List[SearoutePort]:

    unique_locodes = set()
    uniq_ports = []
    for port in ports:
        if port.locode not in unique_locodes:
            unique_locodes.add(port.locode)
            uniq_ports.append(port)

    ports = sorted(uniq_ports, key=lambda p: p.distance, reverse=False)

    return ports
