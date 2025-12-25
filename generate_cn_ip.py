import math
import requests
import json
import os
import ipaddress
import maxminddb
from aggregate6 import aggregate

# 数据源
CHNROUTES2_URL = "https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"
APNIC_URL = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"
MAXMIND_URL = "https://raw.githubusercontent.com/Dreamacro/maxmind-geoip/release/Country.mmdb"

# 输出文件
OUTPUT_JSON = "cn-ip.json"
OUTPUT_SRS = "cn-ip.srs"


def get_chnroutes2() -> list[str]:
    r = requests.get(CHNROUTES2_URL)
    r.raise_for_status()
    return [
        line.strip()
        for line in r.text.splitlines()
        if line and not line.startswith("#")
    ]


def get_apnic_cn() -> list[str]:
    r = requests.get(APNIC_URL)
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
    r = requests.get(MAXMIND_URL)
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


def sort_key(cidr: str):
    net = ipaddress.ip_network(cidr, strict=False)
    return (
        net.version,                     # IPv4 在前，IPv6 在后
        int(net.network_address),         # 网络地址数值
        net.prefixlen                     # 前缀长度
    )


def main():
    all_ip_cidr = []

    # 收集三类 IP
    all_ip_cidr.extend(get_chnroutes2())
    all_ip_cidr.extend(get_apnic_cn())
    all_ip_cidr.extend(get_maxmind_cn())

    # 去重
    all_ip_cidr = list(set(all_ip_cidr))

    # CIDR 聚合
    all_ip_cidr = aggregate(all_ip_cidr)

    # 稳定排序（修复 IPv4 / IPv6 比较问题）
    all_ip_cidr = sorted(all_ip_cidr, key=sort_key)

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

    # 编译为二进制规则
    os.system(
        f"sing-box rule-set compile --output {OUTPUT_SRS} {OUTPUT_JSON}"
    )

    print("Generated:")
    print(OUTPUT_JSON)
    print(OUTPUT_SRS)


if __name__ == "__main__":
    main()
