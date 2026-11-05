domain: network

# Pivoting and lateral movement

After gaining a foothold on one host, pivoting is the act of using that host to
reach network segments that are not directly routable from the attacker's
machine. Techniques include SSH local/remote/dynamic port forwarding, SOCKS
proxies (e.g. via a chisel or ligolo tunnel), and routing tools that inject
routes through the compromised host.

Enumerate the new segment first: ARP tables, routing tables, and listening
services on the pivot host reveal adjacent subnets. Keep tunnels narrow and
documented; note which ports are forwarded so cleanup is complete.

Defensive view: segment networks, restrict east-west traffic, and alert on
hosts that suddenly originate connections to many internal addresses.
