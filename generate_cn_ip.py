import math
import requests
import json
import os
import ipaddress
import maxminddb
from aggregate6 import aggregate

# ======================
# 数据源（全部 CN）
# ======================

CHNROUTES2_URL = "https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"
APNIC_URL = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"
MAXMIND_URL = "https://raw.githubusercontent.com/Dreamacro/maxmind-geoip/release/Country.mmdb"

# ======================
# 输出文件（根目录）
# ======================

OUTPUT_JSON = "cn-ip.json"
OUTPUT_SRS = "cn-ip.srs"


# ======================
# 数据获取
# ======================

def get_chnroutes2() -> list[str]:
    r = requests.get(CHNROUTES2_URL, timeout=60)
    r.raise_for_status()
    return [
        line.strip()
        for line in r.text.splitlines()
        if line and not line.startswith("#")
    ]


def get_apnic_cn() -> list[str]:
    r = requests.get(APNIC_URL, timeout=60)
    r.raise_for_status()

    ip_list = []

    for line in r.text.splitlines():
        if line.startswith("#"):
            continue

        parts = line.split("|")
        if len(parts) < 7:
            continue

        country, ip_type = parts[1], parts[2]
        if country != "CN":
            continue

        if ip_type == "ipv4":
            ip = parts[3]
            count = int(parts[4])
            prefix = 32 - int(math.log2(count))
            ip_list.append(f"{ip}/{prefix}")

        elif ip_type == "ipv6":
            ip = parts[3]
            prefix = parts[4]
            ip_list.append(f"{ip}/{prefix}")

    return ip_list


def get_maxmind_cn() -> list[str]:
    r = requests.get(MAXMIND_URL, timeout=60)
    r.raise_for_status()

    with open("Country.mmdb", "wb") as f:
        f.write(r.content)

    reader = maxminddb.open_database("Country.mmdb")
    ip_list = []

    for cidr, info in reader:
        country = None
        if info.get("country"):
            country = info["country"].get("iso_code")
        elif info.get("registered_country"):
            country = info["registered_country"].get("iso_code")

        if country == "CN":
            ip_list.append(str(cidr))

    reader.close()
    os.remove("Country.mmdb")
    return ip_list


# ======================
# 处理逻辑
# ======================

def sort_key(cidr: str):
    net = ipaddress.ip_network(cidr, strict=False)
    return (
        net.version,             # IPv4 在前，IPv6 在后
        int(net.network_address),
        net.prefixlen
    )


def remove_covered_ipv4(cidrs: list[str]) -> list[str]:
    """
    移除被更大 IPv4 网段完全覆盖的子网
    """
    networks = [
        ipaddress.IPv4Network(c, strict=False)
        for c in cidrs
    ]

    # 按网络地址 + 前缀排序（父网段优先）
    networks.sort(key=lambda n: (int(n.network_address), n.prefixlen))

    result: list[ipaddress.IPv4Network] = []
    for net in networks:
        if not any(net.subnet_of(existing) for existing in result):
            result.append(net)

    return [str(n) for n in result]


# ======================
# 主流程
# ======================

def main():
    all_ip_cidr: list[str] = []

    # 收集三类 CN IP
    all_ip_cidr.extend(get_chnroutes2())
    all_ip_cidr.extend(get_apnic_cn())
    all_ip_cidr.extend(get_maxmind_cn())

    # 去重（字符串级）
    all_ip_cidr = list(set(all_ip_cidr))

    # 拆分 IPv4 / IPv6
    ipv4_list = [c for c in all_ip_cidr if ":" not in c]
    ipv6_list = [c for c in all_ip_cidr if ":" in c]

    # IPv4：聚合 + 去掉被覆盖子网
    ipv4_list = aggregate(ipv4_list)
    ipv4_list = remove_covered_ipv4(ipv4_list)

    # IPv6：不聚合，仅去重 + 排序（最大覆盖）
    ipv6_list = sorted(set(ipv6_list), key=sort_key)

    # 合并并最终排序
    all_ip_cidr = sorted(ipv4_list + ipv6_list, key=sort_key)

    result = {
        "version": 3,
        "rules": [
            {
                "ip_cidr": all_ip_cidr
            }
        ]
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(result, f, indent=2)

    # 编译为 sing-box 二进制规则
    os.system(
        f"sing-box rule-set compile --output {OUTPUT_SRS} {OUTPUT_JSON}"
    )

    print("Generated:")
    print(f"- {OUTPUT_JSON}")
    print(f"- {OUTPUT_SRS}")


if __name__ == "__main__":
    main()
