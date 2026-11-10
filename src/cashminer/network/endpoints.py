"""La clave de peer es la pareja (IP, puerto) de la base de cada red.

NO representa identidad criptográfica permanente del software que escucha.
"""
import ipaddress


def normalize_ip(value: str) -> str:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    ip = ipaddress.ip_address(value)
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)


def endpoint(ip: str, port: int) -> str:
    host = normalize_ip(ip)
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def split_endpoint(value: str, default_port: int | None = None) -> tuple[str, int]:
    value = value.strip()
    if value.startswith("["):
        if "]" not in value:
            raise ValueError("IPv6 requiere [IP]:puerto")
        i = value.index("]")
        host = value[1:i]
        remainder = value[i + 1:]
        if remainder.startswith(":"):
            port = int(remainder[1:])
        elif not remainder and default_port:
            port = int(default_port)
        else:
            raise ValueError("Falta puerto")
    elif value.count(":") == 1:
        host, port_text = value.rsplit(":", 1)
        port = int(port_text)
    elif value.count(":") == 0 and default_port:
        host, port = value, default_port
    else:
        raise ValueError("Usá IPv4:puerto o [IPv6]:puerto")
    if not 1 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")
    return normalize_ip(host), int(port)


def eligible_public_ip(ip: str) -> bool:
    return ipaddress.ip_address(normalize_ip(ip)).is_global
