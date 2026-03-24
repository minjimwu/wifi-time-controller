#!/usr/bin/env python3
"""
Send a Wake-on-WLAN magic packet to wake the suspended laptop.

Usage (from any device on the same network):
  python3 wake.py <MAC_ADDRESS>

Example:
  python3 wake.py XX:XX:XX:XX:XX:XX

Find the laptop's WiFi MAC address:
  ip link show wlp0s20f3 | grep ether
"""
import socket
import sys


def send_magic_packet(mac: str):
    """Send a WoL magic packet to the given MAC address."""
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(mac_bytes) != 6:
        print(f"Invalid MAC address: {mac}")
        sys.exit(1)

    # Magic packet: 6x 0xFF + 16x MAC address
    packet = b"\xff" * 6 + mac_bytes * 16

    # Send via UDP broadcast
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, ("255.255.255.255", 9))

    print(f"Magic packet sent to {mac}")
    print("The laptop should wake up in a few seconds.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    send_magic_packet(sys.argv[1])
