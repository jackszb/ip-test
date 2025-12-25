#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import requests
import json
import os
import ipaddress
import maxminddb
from aggregate6 import aggregate

# ================= 数据源 =================

CHNROUTES2_URL = "https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"
APNIC_URL = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"
MAXMIND_URL = "https://raw.githubusercontent.com/Dreamacro/maxmind-geoip/release/Country.mmdb"

# ================= 输出 =================

OUTPUT_JSON = "cn-ip.json"
OUTPUT_SRS = "cn-ip.srs"

# ========================================


def get_chnroutes2() -> list[str]:
    r = requests.get(CHNROUTES2_URL, timeout=30)
    r.raise_for_status()
    return [
        line.strip()
        for line in r.text.splitlines()
        if line and not line.startswith("#")
    ]


def get_apnic_cn() -> list[str]:
    r = requests.get(APNIC_URL, timeout=30)
    r.raise_for_status()

    result = []

    for line in r.text.splitlines():
        if line.startswith("#"):
            continue

        parts = line.split("|")
        if len(parts) < 7:
            continue

        cc, ip_type = parts[1], parts[2]
        if cc != "CN":
            continue

        if ip_type == "ipv4":
            ip = parts[3]
            count = int(parts[4])
            prefix = 32 - int(math.log2(count))
            result.append(f"{ip}/{prefix}")

        elif ip_type == "ipv6":
            ip = parts[3]
            prefix = parts[4]
            result.append(f"{ip}/{prefix}")

    return result


def get_maxmind_cn() -> list[str]:
    r = requests.get(MAXMIND_URL, timeout=30)
    r.raise_for_status()

    mmdb_file = "Country.mmdb"
    with open(mmdb_file, "wb") as f:
        f.write(r.content)

    reader = maxminddb.open_database(mmdb_file)
    result = []

    for cidr, info in reader:
        country = None
        if info.get("country"):
            country = info["country"].get("iso_code")
        elif info.get("registered_country"):
            country = info["registered_country"].get("iso_code")

        if country == "CN":
            result.append(str(cidr))

    reader.close()
    os.remove(mmdb_file)
    return result


def main():
    raw_list: list[str] = []

    raw_list.extend(get_chnroutes2())
    raw_list.extend(get_apnic_cn())
    raw_list.extend(get_maxmind_cn())

    # 去重
    raw_list = list(set(raw_list))

    # === 聚合（返回 ip_network 对象）===
    aggregated = aggregate(raw_list)

    ipv4_set: set[ipaddress.IPv4Network] = set()
    ipv6_set: set[ipaddress.IPv6Network] = set()

    for net in aggregated:
        if isinstance(net, str):
            net = ipaddress.ip_network(net, strict=False)

        if net.version == 4:
            ipv4_set.add(net)
        else:
            ipv6_set.add(net)

    # === 关键修复：IPv4 / IPv6 分开排序 ===
    ipv4_sorted = sorted(
        ipv4_set,
        key=lambda n: (int(n.network_address), n.prefixlen),
    )
    ipv6_sorted = sorted(
        ipv6_set,
        key=lambda n: (int(n.network_address), n.prefixlen),
    )

    all_ip_cidr = [str(n) for n in ipv4_sorted + ipv6_sorted]

    result = {
        "version": 3,
        "rules": [
            {
                "ip_cidr": all_ip_cidr
            }
        ]
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # 编译 sing-box 二进制规则
    os.system(f"sing-box rule-set compile --output {OUTPUT_SRS} {OUTPUT_JSON}")

    print("Generated:")
    print(OUTPUT_JSON)
    print(OUTPUT_SRS)


if __name__ == "__main__":
    main()
