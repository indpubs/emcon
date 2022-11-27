import argparse
import pathlib
import sys
from . import report
from dali.address import GearShort, GearBroadcast
from dali.gear.emergency import (
    Inhibit,
    Rest,
    ReLightResetInhibit,
    StartFunctionTest,
    StartDurationTest,
    StopTest,
)


def main():
    parser = argparse.ArgumentParser(
        description="Emergency lighting control")
    parser.add_argument(
        '--configfile', '-c', type=pathlib.Path,
        default=pathlib.Path("config.toml"),
        help="Path to configuration file")
    parser.add_argument(
        '--site', '-s', type=str, action="append",
        help="Only work on this site")
    parser.add_argument(
        '--verbose', '-v', action="store_true", default=False,
        help="Display progress while working")
    parser.add_argument(
        'action', type=str, nargs="?", choices=list(actions.keys()),
        default="list", help="Action to perform")
    parser.add_argument(
        'target', type=str, nargs="?", help="Target of action")

    args = parser.parse_args()

    try:
        with open(args.configfile, "rb") as f:
            report.read_config(f)
    except FileNotFoundError:
        print(f"Could not open config file '{args.configfile}'")
        sys.exit(1)

    if args.site:
        try:
            report.sites = {s: report.sites[s] for s in args.site}
        except KeyError as e:
            print(f"Unrecognised site '{e.args[0]}'")
            sys.exit(1)

    actions[args.action](args)


def list_gear(args):
    for sitename, site in report.sites.items():
        for gear in site.gear:
            print(f"{sitename}/{gear.busname}/{gear.address}: {gear.name}")


def check(args):
    for sitename, site in report.sites.items():
        print(f"Site: {site.name}")
        if args.verbose:
            print(f"  - Rated duration: {site.expected_rated_duration} "
                  f"minutes")
            print(f"  - Function test every {site.expected_ft_interval} days")
            print(f"  - Duration test every {site.expected_dt_interval} weeks")
            print(f"  - Test required to complete within "
                  f"{site.expected_timeout} days of scheduled time")
            print("  - Gear:")

        def progress(gear):
            if args.verbose:
                print(f"    - {sitename}/{gear.busname}/{gear.address} — "
                      f"{gear.summary}")
                gear.dump_state(indent=8)

        site.update(progress=progress)

        print(f"  - Overall state: {'Pass' if site.pass_ else 'Fail'}")
        print(f"  - Results: {site.results}")


def email(args):
    for sitename, site in report.sites.items():
        if args.verbose:
            print(f"Site: {site.name}")

        def progress(gear):
            if args.verbose:
                print(f"  - {sitename}/{gear.busname}/{gear.address} — "
                      f"{gear.summary}")

        site.update(progress=progress)
        if args.target:
            site.email_report(sitename, to=args.target)
        else:
            site.email_report(sitename)


def _send_command(command, target):
    # Target can be:
    #  sitename                  broadcast on all buses at sitename
    #  sitename/busname          broadcast on this bus at sitename
    #  sitename/busname/address  send to particular address on this bus
    if not target:
        print("Target must be specified")
        sys.exit(1)
    ts = target.split('/')
    if len(ts) > 3:
        print("Target must be sitename[/busname[/address]]")
        sys.exit(1)
    site = report.sites.get(ts[0])
    if not site:
        print(f"Site {ts[0]} not known")
        sys.exit(1)
    if len(ts) > 1:
        bus = site.buses.get(ts[1], None)
        if not bus:
            print(f"Bus {ts[1]} not known at site {ts[0]}")
            sys.exit(1)
        buses = [bus]
    else:
        buses = list(site.buses.values())
    if len(ts) > 2:
        address = GearShort(int(ts[2]))
    else:
        address = GearBroadcast()
    for bus in buses:
        with bus as b:
            b.send(command(address))


def inhibit(args):
    _send_command(Inhibit, args.target)


def rest(args):
    _send_command(Rest, args.target)


def reset(args):
    _send_command(ReLightResetInhibit, args.target)


def start_function_test(args):
    _send_command(StartFunctionTest, args.target)


def start_duration_test(args):
    _send_command(StartDurationTest, args.target)


def stop_test(args):
    _send_command(StopTest, args.target)


actions = {
    'list': list_gear,
    'check': check,
    'email': email,
    'inhibit': inhibit,
    'rest': rest,
    'reset': reset,
    'start-function-test': start_function_test,
    'start-duration-test': start_duration_test,
    'stop-test': stop_test,
}
