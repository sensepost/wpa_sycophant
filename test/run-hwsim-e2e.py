#!/usr/bin/env python3
"""Run the wpa_sycophant PEAP relay end to end on mac80211_hwsim."""

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


TEST_DIR = Path(__file__).resolve().parent
SOURCE_DIR = TEST_DIR.parent
DEFAULT_HOSTAPD_SRC = SOURCE_DIR.parent / "hostapd-mana"


class TestFailure(Exception):
    pass


def command(args, check=True, timeout=10):
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TestFailure("{} failed: {}".format(" ".join(map(str, args)),
                                                 error))
    if check and result.returncode != 0:
        raise TestFailure("{} failed ({}):\n{}".format(
            " ".join(map(str, args)), result.returncode, result.stdout))
    return result


def namespace_command(ip, netns, args, check=True, timeout=10):
    return command([ip, "netns", "exec", netns] + list(args),
                   check=check, timeout=timeout)


def render(template, output, values):
    contents = template.read_text()
    for key, value in values.items():
        contents = contents.replace("@{}@".format(key), str(value))
    if re.search(r"@[A-Z_]+@", contents):
        raise TestFailure("Unexpanded setting in {}".format(template))
    output.write_text(contents)


def start_process(label, args, log_dir, processes, prefix=None):
    log_path = log_dir / (label + ".log")
    log_file = log_path.open("w")
    try:
        proc = subprocess.Popen((prefix or []) + list(args), stdout=log_file,
                                stderr=subprocess.STDOUT, text=True)
    except OSError as error:
        log_file.close()
        raise TestFailure("Could not start {}: {}".format(label, error))
    processes.append((label, proc, log_file, log_path))
    time.sleep(0.2)
    if proc.poll() is not None:
        raise TestFailure("{} exited during startup; see {}".format(
            label, log_path))
    print("Started {} (pid {})".format(label, proc.pid))
    return proc


def stop_processes(processes):
    for _, proc, _, _ in reversed(processes):
        if proc.poll() is None:
            proc.terminate()
    for _, proc, log_file, _ in reversed(processes):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log_file.close()


def tail_logs(log_dir, lines=80):
    for log_path in sorted(log_dir.glob("*.log")):
        print("\n--- {} ({}) ---".format(log_path.stem, log_path))
        try:
            content = log_path.read_text(errors="replace").splitlines()
            print("\n".join(content[-lines:]))
        except OSError as error:
            print("Could not read log: {}".format(error))


def wait_for_hostapd(ip, netns, hostapd_cli, ctrl_dir, iface, process,
                     timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise TestFailure("hostapd exited on {}".format(iface))
        result = namespace_command(
            ip, netns, [hostapd_cli, "-p", ctrl_dir, "-i", iface, "ping"],
            check=False)
        if result.returncode == 0 and "PONG" in result.stdout:
            return
        time.sleep(0.25)
    raise TestFailure("hostapd did not become ready on {}".format(iface))


def ap_bssid(ip, netns, hostapd_cli, ctrl_dir, iface):
    result = namespace_command(
        ip, netns, [hostapd_cli, "-p", ctrl_dir, "-i", iface, "status"])
    for line in result.stdout.splitlines():
        match = re.match(r"\s*bssid(?:\[0\])?=([0-9a-fA-F:]{17})\s*$",
                         line)
        if match:
            return match.group(1).lower()
    raise TestFailure("Could not read hostapd BSSID for {}".format(iface))


def supplicant_status(ip, netns, wpa_cli, ctrl_dir, iface):
    result = namespace_command(
        ip, netns, [wpa_cli, "-p", ctrl_dir, "-i", iface, "status"],
        check=False)
    if result.returncode != 0:
        return {}
    status = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            status[key] = value
    return status


def wait_for_log(log_path, text, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            contents = log_path.read_text(errors="replace")
        except OSError:
            contents = ""
        if text in contents:
            return
        time.sleep(0.25)
    raise TestFailure("Timed out waiting for {!r} in {}".format(text,
                                                                 log_path))


def set_ip(ip, netns, iface, address):
    namespace_command(ip, netns, ["ip", "address", "add", address, "dev",
                                  iface])


def ping_from(ip, netns, ping, iface, address):
    result = namespace_command(
        ip, netns, [ping, "-n", "-I", iface, "-c", "3", "-W", "3", address],
        check=False, timeout=15)
    if result.returncode != 0:
        details = []
        for args in (["ip", "address", "show", "dev", iface],
                     ["ip", "route", "get", address],
                     ["ip", "neigh", "show", "dev", iface]):
            state = namespace_command(ip, netns, args, check=False)
            details.append("$ {}\n{}".format(
                " ".join(args), state.stdout.strip()))
        raise TestFailure("{}\n{}".format(
            result.stdout.strip(), "\n".join(details)))
    print(result.stdout.strip())


def validate_binaries(args):
    paths = {
        "wpa_supplicant": args.wpa_supplicant_bin,
        "wpa_cli": args.wpa_cli_bin,
        "hostapd": args.hostapd_bin,
        "hostapd_cli": args.hostapd_cli_bin,
    }
    missing = [name for name, path in paths.items()
               if not path.is_file() or not os.access(path, os.X_OK)]
    if missing:
        raise TestFailure(
            "Missing built {}. See test/README.md for build instructions."
            .format(", ".join(missing)))
    if not args.hwsim_dir.is_dir():
        raise TestFailure("hwsim helpers not found: {}".format(args.hwsim_dir))
    for tool in ("ip", "iw", "ping"):
        if shutil.which(tool) is None:
            raise TestFailure("Required command not found: {}".format(tool))


def create_radios(stack, hwsim_dir, ip, iw, radio_namespaces):
    sys.path.insert(0, str(hwsim_dir))
    try:
        from hwsim import HWSimRadio
    except ImportError as error:
        raise TestFailure("Could not import hwsim radio helper: {}".format(
            error))

    radios = []
    phys = []
    nmcli = shutil.which("nmcli")
    try:
        for index in range(4):
            radio_id, iface = stack.enter_context(HWSimRadio())
            if nmcli:
                command([nmcli, "device", "set", iface, "managed", "no"],
                        check=False)
            command([ip, "link", "set", "dev", iface, "down"],
                    check=False)
            test_iface = "wsim{}".format(index)
            command([ip, "link", "set", "dev", iface, "name", test_iface])
            info = command([iw, "dev", test_iface, "info"])
            match = re.search(r"^\s*wiphy\s+(\d+)\s*$", info.stdout,
                              re.MULTILINE)
            if not match:
                raise TestFailure("Could not find phy for {}".format(
                    test_iface))
            phy = "phy{}".format(match.group(1))
            netns = radio_namespaces[index]
            command([iw, "phy", phy, "set", "netns", "name", netns])
            radios.append(test_iface)
            phys.append((phy, netns))
            print("Created hwsim radio {} ({}, {}) in {}".format(
                radio_id, test_iface, phy, netns))
    except Exception as error:
        raise TestFailure("Could not create four hwsim radios: {}".format(
            error))
    return radios, phys


def run_test(args, log_dir):
    validate_binaries(args)
    auth_dir = args.hwsim_dir / "auth_serv"
    for fixture in ("ca.pem", "server.pem", "server.key"):
        if not (auth_dir / fixture).is_file():
            raise TestFailure("Missing hwsim certificate fixture: {}".format(
                auth_dir / fixture))

    processes = []
    stack = ExitStack()
    netns_base = "wpa-sycophant-e2e-{}".format(os.getpid())
    ap_netns = netns_base + "-ap"
    victim_netns = netns_base + "-victim"
    syco_netns = netns_base + "-syco"
    netns_created = []
    phys = []
    try:
        for netns in (ap_netns, victim_netns, syco_netns):
            command([args.ip, "netns", "add", netns])
            netns_created.append(netns)
        radios, phys = create_radios(
            stack, args.hwsim_dir, args.ip, args.iw,
            [ap_netns, ap_netns, victim_netns, syco_netns])
        rogue_ap, target_ap, victim_sta, syco_sta = radios
        ap_ctrl = log_dir / "hostapd-ctrl"
        victim_ctrl = log_dir / "victim-ctrl"
        syco_ctrl = log_dir / "sycophant-ctrl"
        for ctrl_dir in (ap_ctrl, victim_ctrl, syco_ctrl):
            ctrl_dir.mkdir(mode=0o700)

        socket_path = log_dir / "sycophant.sock"
        common_ap_values = {
            "CTRL_INTERFACE": ap_ctrl,
            "EAP_USER_FILE": TEST_DIR / "eap_user.conf",
            "CA_CERT": auth_dir / "ca.pem",
            "SERVER_CERT": auth_dir / "server.pem",
            "PRIVATE_KEY": auth_dir / "server.key",
        }
        rogue_conf = log_dir / "hostapd-rogue.conf"
        render(TEST_DIR / "hostapd.conf.in", rogue_conf, dict(
            common_ap_values,
            INTERFACE=rogue_ap,
            MANA_OPTIONS="\n".join([
                "enable_mana=1",
                "mana_loud=1",
                "enable_sycophant=1",
                "sycophant_socket={}".format(socket_path),
            ])))
        target_conf = log_dir / "hostapd-target.conf"
        render(TEST_DIR / "hostapd.conf.in", target_conf, dict(
            common_ap_values, INTERFACE=target_ap, MANA_OPTIONS=""))

        rogue = start_process("hostapd-rogue",
                              [str(args.hostapd_bin), "-dd", str(rogue_conf)],
                              log_dir, processes,
                              prefix=[args.ip, "netns", "exec", ap_netns])
        target = start_process("hostapd-target",
                               [str(args.hostapd_bin), "-dd",
                                str(target_conf)], log_dir, processes,
                               prefix=[args.ip, "netns", "exec", ap_netns])
        wait_for_hostapd(args.ip, ap_netns, args.hostapd_cli_bin,
                         str(ap_ctrl), rogue_ap, rogue)
        wait_for_hostapd(args.ip, ap_netns, args.hostapd_cli_bin,
                         str(ap_ctrl), target_ap, target)
        rogue_bssid = ap_bssid(args.ip, ap_netns, args.hostapd_cli_bin,
                               str(ap_ctrl), rogue_ap)
        target_bssid = ap_bssid(args.ip, ap_netns, args.hostapd_cli_bin,
                                str(ap_ctrl), target_ap)
        print("Rogue MANA AP: {} ({})".format(rogue_ap, rogue_bssid))
        print("Legitimate AP: {} ({})".format(target_ap, target_bssid))

        set_ip(args.ip, ap_netns, rogue_ap, "198.51.100.1/24")
        set_ip(args.ip, ap_netns, target_ap, "192.0.2.1/24")
        set_ip(args.ip, victim_netns, victim_sta, "198.51.100.2/24")
        set_ip(args.ip, syco_netns, syco_sta, "192.0.2.2/24")

        victim_conf = log_dir / "wpa_supplicant-victim.conf"
        render(TEST_DIR / "wpa_supplicant-victim.conf.in", victim_conf, {
            "CTRL_INTERFACE": victim_ctrl,
            "BSSID": rogue_bssid,
            "CA_CERT": auth_dir / "ca.pem",
        })
        syco_conf = log_dir / "wpa_supplicant-sycophant.conf"
        render(TEST_DIR / "wpa_supplicant-sycophant.conf.in", syco_conf, {
            "CTRL_INTERFACE": syco_ctrl,
            "BSSID": target_bssid,
            "CA_CERT": auth_dir / "ca.pem",
        })

        print("Starting victim association to the rogue AP")
        start_process(
            "victim",
            [str(args.wpa_supplicant_bin), "-dd", "-D", "nl80211",
             "-i", victim_sta, "-c", str(victim_conf)],
            log_dir, processes,
            prefix=[args.ip, "netns", "exec", victim_netns])
        print("Victim association is in progress; starting sycophant")
        start_process(
            "sycophant",
            [str(args.wpa_supplicant_bin), "-dd", "-D", "nl80211",
             "-i", syco_sta, "-c", str(syco_conf), "-S", str(socket_path)],
            log_dir, processes,
            prefix=[args.ip, "netns", "exec", syco_netns])
        wait_for_log(log_dir / "sycophant.log", "CTRL-EVENT-CONNECTED",
                     args.timeout)
        wait_for_log(log_dir / "victim.log", "CTRL-EVENT-CONNECTED",
                     args.timeout)

        for label, netns, ctrl_dir, iface, expected_bssid in (
                ("victim", victim_netns, victim_ctrl, victim_sta,
                 rogue_bssid),
                ("sycophant", syco_netns, syco_ctrl, syco_sta,
                 target_bssid)):
            status = supplicant_status(args.ip, netns, args.wpa_cli_bin,
                                       str(ctrl_dir), iface)
            if status.get("wpa_state") != "COMPLETED":
                raise TestFailure("{} is not connected: {}".format(label,
                                                                    status))
            if status.get("bssid", "").lower() != expected_bssid:
                raise TestFailure("{} connected to unexpected BSSID: {}"
                                  .format(label, status))
            print("{} connected to {} ({}): {}".format(
                label, status.get("ssid"), expected_bssid,
                status.get("wpa_state")))

        syco_log = (log_dir / "sycophant.log").read_text(errors="replace")
        rogue_log = (log_dir / "hostapd-rogue.log").read_text(
            errors="replace")
        if "accepting relayed MSCHAPv2 success" not in syco_log:
            raise TestFailure("Sycophant did not accept a relayed MSCHAPv2 "
                              "success response")
        if "SYCOPHANT: Relayed MSCHAPv2 challenge" not in rogue_log:
            raise TestFailure("MANA AP did not receive a relayed MSCHAPv2 "
                              "challenge")

        print("Checking victim connectivity to the rogue AP")
        ping_from(args.ip, victim_netns, args.ping, victim_sta,
                  "198.51.100.1")
        print("Checking sycophant connectivity to the legitimate AP")
        ping_from(args.ip, syco_netns, args.ping, syco_sta, "192.0.2.1")
        print("PASS: PEAP relay and both AP connectivity checks succeeded")
    finally:
        stop_processes(processes)
        for phy, netns in phys:
            namespace_command(args.ip, netns,
                              [args.iw, "phy", phy, "set", "netns", "1"],
                              check=False)
        stack.close()
        for netns in reversed(netns_created):
            command([args.ip, "netns", "del", netns], check=False)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostapd-src", type=Path, default=DEFAULT_HOSTAPD_SRC,
                        help="hostapd-mana source checkout")
    parser.add_argument("--hwsim-dir", type=Path,
                        help="hwsim test directory (defaults to "
                             "<hostapd-src>/tests/hwsim)")
    parser.add_argument("--hostapd-bin", type=Path,
                        help="built hostapd binary")
    parser.add_argument("--hostapd-cli-bin", type=Path,
                        help="built hostapd_cli binary")
    parser.add_argument("--wpa-supplicant-bin", type=Path,
                        help="built wpa_supplicant binary")
    parser.add_argument("--wpa-cli-bin", type=Path,
                        help="built wpa_cli binary")
    parser.add_argument("--timeout", type=int, default=90,
                        help="seconds to wait for each station to connect")
    parser.add_argument("--keep-logs", action="store_true",
                        help="keep generated configs and logs after success")
    args = parser.parse_args()

    args.hostapd_src = args.hostapd_src.resolve()
    args.hwsim_dir = (args.hwsim_dir or
                      args.hostapd_src / "tests" / "hwsim").resolve()
    args.hostapd_bin = (args.hostapd_bin or
                        args.hostapd_src / "hostapd" / "hostapd").resolve()
    args.hostapd_cli_bin = (args.hostapd_cli_bin or
                            args.hostapd_src / "hostapd" /
                            "hostapd_cli").resolve()
    args.wpa_supplicant_bin = (args.wpa_supplicant_bin or
                               SOURCE_DIR / "wpa_supplicant" /
                               "wpa_supplicant").resolve()
    args.wpa_cli_bin = (args.wpa_cli_bin or
                        SOURCE_DIR / "wpa_supplicant" / "wpa_cli").resolve()
    args.ip = shutil.which("ip")
    args.iw = shutil.which("iw")
    args.ping = shutil.which("ping")
    return args


def main():
    args = parse_args()
    if os.geteuid() != 0:
        print("Run this test as root (for example, with sudo).", file=sys.stderr)
        return 2

    log_dir = Path(tempfile.mkdtemp(prefix="wpa-sycophant-hwsim-"))
    failed = False
    try:
        run_test(args, log_dir)
    except Exception as error:
        failed = True
        print("FAIL: {}".format(error), file=sys.stderr)
        tail_logs(log_dir)
        print("\nRun artifacts: {}".format(log_dir), file=sys.stderr)
        return 1
    finally:
        if failed or args.keep_logs:
            print("Run artifacts: {}".format(log_dir))
        else:
            shutil.rmtree(log_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
